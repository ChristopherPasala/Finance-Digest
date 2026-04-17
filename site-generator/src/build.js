const ejs = require('ejs');
const fs = require('fs');
const path = require('path');
const { getAllPosts, getPostBySlug } = require('./db');

const glossaryTerms = require('./glossary.json');

// Pre-sort longest terms first to avoid "EBITDA" matching inside "EV/EBITDA"
const sortedTerms = [...glossaryTerms].sort((a, b) => b.term.length - a.term.length);

function termAnchor(term) {
  return term.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

/**
 * Post-process HTML to hyperlink the first occurrence of each glossary term
 * in text nodes only (not inside existing <a> tags or heading tags).
 */
function applyGlossaryLinks(html) {
  // Split HTML into alternating [text, tag, text, tag, ...] segments
  // Tags match <...> including attributes; we only modify text segments.
  const parts = html.split(/(<[^>]+>)/);

  // Track whether we're inside an <a> or any heading tag (skip linking there)
  let depth = { a: 0, h1: 0, h2: 0, h3: 0, h4: 0, h5: 0, h6: 0 };

  return parts.map(part => {
    // It's a tag — update depth tracking, return as-is
    if (part.startsWith('<')) {
      const tag = part.match(/^<\/?([a-z][a-z0-9]*)/i);
      if (tag) {
        const name = tag[1].toLowerCase();
        if (name in depth) {
          depth[name] += part.startsWith('</') ? -1 : 1;
        }
      }
      return part;
    }

    // It's a text node — skip if inside a link or any heading
    if (depth.a > 0 || depth.h1 > 0 || depth.h2 > 0 ||
        depth.h3 > 0 || depth.h4 > 0 || depth.h5 > 0 || depth.h6 > 0) return part;

    // Apply glossary links to every occurrence of each term.
    // Re-split by tags before each term so subsequent terms cannot match
    // inside href attributes or link text introduced by earlier iterations.
    let result = part;
    for (const { term } of sortedTerms) {
      const anchor = termAnchor(term);
      const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`(?<![\\w/])${escaped}(?![\\w/])`, 'gi');

      // Split result into [text, tag, text, tag, ...] to avoid matching
      // inside tag attributes or link text introduced by earlier iterations.
      const subParts = result.split(/(<[^>]+>)/);
      let aDepth = 0;
      result = subParts.map(sub => {
        if (sub.startsWith('<')) {
          const tag = sub.match(/^<\/?([a-z][a-z0-9]*)/i);
          if (tag && tag[1].toLowerCase() === 'a') {
            aDepth += sub.startsWith('</') ? -1 : 1;
          }
          return sub; // tag — never modify
        }
        if (aDepth > 0) return sub; // inside an existing link — skip
        return sub.replace(regex, m =>
          `<a href="/glossary.html#${anchor}" class="glossary-link">${m}</a>`
        );
      }).join('');
    }
    return result;
  }).join('');
}

const TEMPLATES = path.join(__dirname, '..', 'templates');
const PUBLIC = path.join(__dirname, '..', 'public');

function readTemplate(name) {
  return fs.readFileSync(path.join(TEMPLATES, name), 'utf8');
}

const isBriefing = slug => slug.startsWith('daily-') || slug.startsWith('portfolio-');
const isScan = slug => slug.startsWith('scan-');

function renderLayout(title, bodyHtml, { showBack = false, activeTab = 'analyses', generatedAt } = {}) {
  return ejs.render(readTemplate('layout.html'), {
    title,
    body: bodyHtml,
    show_back: showBack,
    active_tab: activeTab,
    generated_at: generatedAt || new Date().toUTCString(),
  });
}

function buildPost(post) {
  const outPath = path.join(PUBLIC, 'posts', `${post.slug}.html`);
  // Posts registered by Python have an empty body — their HTML is already on disk.
  // Apply glossary links to the existing file without re-rendering the template.
  if (!post.body) {
    if (fs.existsSync(outPath)) {
      let html = fs.readFileSync(outPath, 'utf8');
      html = applyGlossaryLinks(html);
      fs.writeFileSync(outPath, html);
      console.log(`  Glossary-linked (python-managed): posts/${post.slug}.html`);
    }
    return;
  }
  const bodyHtml = ejs.render(readTemplate('article.html'), { post });
  const activeTab = isScan(post.slug) ? 'scans' : isBriefing(post.slug) ? 'briefings' : 'analyses';
  let html = renderLayout(post.title, bodyHtml, { showBack: true, activeTab });
  html = applyGlossaryLinks(html);
  fs.writeFileSync(outPath, html);
  console.log(`  Built: posts/${post.slug}.html`);
}

function buildIndex(posts) {
  const analyses = posts.filter(p => !isBriefing(p.slug) && !isScan(p.slug));
  const bodyHtml = ejs.render(readTemplate('index.html'), { posts: analyses });
  const html = renderLayout('Company Analyses', bodyHtml, { activeTab: 'analyses' });
  fs.writeFileSync(path.join(PUBLIC, 'index.html'), html);
  console.log('  Built: index.html');
}

function buildScansIndex(posts) {
  const scans = posts.filter(p => isScan(p.slug))
    .sort((a, b) => b.slug.localeCompare(a.slug)); // newest first
  const latestScan = scans[0] || null;
  const historicalScans = scans.slice(1);
  const bodyHtml = ejs.render(readTemplate('scans.html'), { latestScan, historicalScans });
  const html = renderLayout('Market Scans', bodyHtml, { activeTab: 'scans' });
  fs.writeFileSync(path.join(PUBLIC, 'scans.html'), html);
  console.log('  Built: scans.html');
}

function buildGlossary() {
  const bodyHtml = ejs.render(readTemplate('glossary.html'), { terms: glossaryTerms });
  const html = renderLayout('Financial Glossary', bodyHtml, { activeTab: 'glossary' });
  fs.writeFileSync(path.join(PUBLIC, 'glossary.html'), html);
  console.log('  Built: glossary.html');
}

function extractTodayScores() {
  const postsDir = path.join(PUBLIC, 'posts');
  const latest = fs.readdirSync(postsDir)
    .filter(f => f.startsWith('daily-') && f.endsWith('.html'))
    .sort()
    .at(-1);
  if (!latest) return [];

  const html = fs.readFileSync(path.join(postsDir, latest), 'utf8');
  const tickers = [...html.matchAll(/class="opp-tkr">([A-Z0-9.]+)</g)].map(m => m[1]);
  if (!tickers.length) return [];

  let scores;
  if (html.includes('data-score=')) {
    scores = [...html.matchAll(/data-score="(\d+)"/g)].map(m => parseInt(m[1]));
  } else {
    scores = [...html.matchAll(/class="opp-score-num"[^>]*>(\d+)</g)].map(m => parseInt(m[1]));
  }

  return tickers
    .map((ticker, i) => ({ ticker, score: scores[i] ?? 0 }))
    .sort((a, b) => b.score - a.score);
}

function buildBriefingsIndex(posts) {
  const briefings = posts.filter(p => isBriefing(p.slug));
  const todayScores = extractTodayScores();
  const bodyHtml = ejs.render(readTemplate('briefings.html'), { briefings, todayScores });
  const html = renderLayout('Briefings', bodyHtml, { activeTab: 'briefings' });
  fs.writeFileSync(path.join(PUBLIC, 'briefings.html'), html);
  console.log('  Built: briefings.html');
}

// Parse --slug=<value> from argv
const slugArg = process.argv.find(a => a.startsWith('--slug='));
const targetSlug = slugArg ? slugArg.split('=')[1] : null;

if (targetSlug) {
  console.log(`Building single page: ${targetSlug}`);
  const post = getPostBySlug(targetSlug);
  if (!post) {
    console.error(`No post found with slug: ${targetSlug}`);
    process.exit(1);
  }
  const allPosts = getAllPosts();
  buildPost(post);
  if (isScan(targetSlug)) buildScansIndex(allPosts);
  else if (isBriefing(targetSlug)) buildBriefingsIndex(allPosts);
  else buildIndex(allPosts);
  console.log('Done.');
} else {
  console.log('Building all pages...');
  const posts = getAllPosts();
  for (const post of posts) {
    buildPost(post);
  }
  buildIndex(posts);
  buildScansIndex(posts);
  buildBriefingsIndex(posts);
  buildGlossary();
  console.log(`Done. ${posts.length} page(s) built.`);
}
