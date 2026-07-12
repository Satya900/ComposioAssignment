"""
HTML Report Generator

Reads final pipeline data and generates a single self-contained HTML page
with all data embedded inline. The page is the primary deliverable.
"""

import json
from pathlib import Path
from typing import Optional

from agent.config import FINAL_DIR, SITE_DIR
from agent.schemas import AccuracyReport, AppResearchResult, PatternReport
from agent.utils import get_logger, load_json

logger = get_logger()


def generate_html_report(
    results: list[AppResearchResult],
    patterns: PatternReport,
    accuracy: Optional[AccuracyReport] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Generate the full HTML report page.
    Embeds all data inline — no external API calls needed.
    """
    output_path = output_path or str(SITE_DIR / "index.html")
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    # Serialize data for embedding
    results_json = json.dumps(
        [r.model_dump() if hasattr(r, "model_dump") else r for r in results],
        default=str,
        ensure_ascii=False,
    )
    patterns_json = json.dumps(
        patterns.model_dump() if hasattr(patterns, "model_dump") else patterns,
        default=str,
        ensure_ascii=False,
    )
    accuracy_json = json.dumps(
        accuracy.model_dump() if accuracy and hasattr(accuracy, "model_dump") else {},
        default=str,
        ensure_ascii=False,
    )

    # Quick stats for hero section
    total = len(results)
    easy_count = sum(1 for r in results if r.buildability == "easy")
    mcp_count = sum(1 for r in results if r.has_existing_mcp)
    self_serve_count = sum(1 for r in results if r.self_serve)

    from collections import Counter
    auth_dist = Counter(r.auth_primary for r in results)
    top_auth = auth_dist.most_common(1)[0] if auth_dist else ("N/A", 0)
    top_auth_pct = round(top_auth[1] / total * 100) if total else 0

    first_pass_acc = accuracy.first_pass_accuracy if accuracy else 0
    final_acc = accuracy.final_accuracy if accuracy else 0

    html = _build_html(
        results_json=results_json,
        patterns_json=patterns_json,
        accuracy_json=accuracy_json,
        total=total,
        easy_count=easy_count,
        mcp_count=mcp_count,
        self_serve_count=self_serve_count,
        top_auth=top_auth[0],
        top_auth_pct=top_auth_pct,
        first_pass_acc=first_pass_acc,
        final_acc=final_acc,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"🌐 HTML report generated: {output_path}")
    return output_path


def _build_html(**kwargs) -> str:
    """Build the complete HTML string."""
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Composio App Research: 100 Apps Analyzed by AI Agent</title>
    <meta name="description" content="AI-powered research pipeline analyzing 100 SaaS apps for API surface, authentication, access models, and agent-toolkit buildability for Composio.">

    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            darkMode: 'class',
            theme: {{
                extend: {{
                    colors: {{
                        brand: {{ 50: '#f0f4ff', 100: '#dbe4ff', 200: '#bac8ff', 300: '#91a7ff', 400: '#748ffc', 500: '#5c7cfa', 600: '#4c6ef5', 700: '#4263eb', 800: '#3b5bdb', 900: '#364fc7' }},
                    }},
                    fontFamily: {{
                        sans: ['Inter', 'system-ui', 'sans-serif'],
                    }},
                }}
            }}
        }}
    </script>

    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">

    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>

    <style>
        * {{ scroll-behavior: smooth; }}
        body {{ font-family: 'Inter', system-ui, sans-serif; }}

        /* Custom scrollbar */
        ::-webkit-scrollbar {{ width: 8px; }}
        ::-webkit-scrollbar-track {{ background: #1e293b; }}
        ::-webkit-scrollbar-thumb {{ background: #475569; border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: #64748b; }}

        /* Glassmorphism card */
        .glass-card {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(71, 85, 105, 0.3);
        }}

        /* Buildability badges */
        .badge-easy {{ background: #065f46; color: #6ee7b7; }}
        .badge-moderate {{ background: #713f12; color: #fcd34d; }}
        .badge-hard {{ background: #7c2d12; color: #fdba74; }}
        .badge-not_feasible {{ background: #7f1d1d; color: #fca5a5; }}

        /* Table row hover */
        .app-row:hover {{ background: rgba(71, 85, 105, 0.3); }}
        .app-row {{ transition: background 0.15s ease; }}

        /* Expandable detail */
        .app-detail {{ max-height: 0; overflow: hidden; transition: max-height 0.3s ease; }}
        .app-detail.open {{ max-height: 600px; }}

        /* Stat card hover */
        .stat-card {{ transition: transform 0.2s ease, box-shadow 0.2s ease; }}
        .stat-card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,0,0,0.3); }}

        /* Sticky nav */
        .sticky-nav {{ position: sticky; top: 0; z-index: 50; backdrop-filter: blur(12px); background: rgba(15, 23, 42, 0.85); }}

        /* Print styles */
        @media print {{
            .sticky-nav, .no-print {{ display: none; }}
            .glass-card {{ background: white; border: 1px solid #ddd; color: #333; }}
            body {{ background: white; color: #333; }}
        }}

        /* Pulse animation for hero stats */
        @keyframes fadeInUp {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .animate-fade-in {{ animation: fadeInUp 0.6s ease forwards; }}
        .animate-delay-1 {{ animation-delay: 0.1s; opacity: 0; }}
        .animate-delay-2 {{ animation-delay: 0.2s; opacity: 0; }}
        .animate-delay-3 {{ animation-delay: 0.3s; opacity: 0; }}
        .animate-delay-4 {{ animation-delay: 0.4s; opacity: 0; }}
        .animate-delay-5 {{ animation-delay: 0.5s; opacity: 0; }}
    </style>
</head>
<body class="bg-slate-950 text-slate-200 min-h-screen">

    <!-- Embedded Data -->
    <script>
        const RESULTS = {kwargs['results_json']};
        const PATTERNS = {kwargs['patterns_json']};
        const ACCURACY = {kwargs['accuracy_json']};
    </script>

    <!-- Sticky Navigation -->
    <nav class="sticky-nav border-b border-slate-800 px-6 py-3">
        <div class="max-w-7xl mx-auto flex items-center justify-between">
            <span class="text-sm font-semibold text-brand-400">Composio Research</span>
            <div class="flex gap-6 text-sm text-slate-400">
                <a href="#findings" class="hover:text-white transition">Findings</a>
                <a href="#patterns" class="hover:text-white transition">Patterns</a>
                <a href="#matrix" class="hover:text-white transition">Matrix</a>
                <a href="#data" class="hover:text-white transition">Data</a>
                <a href="#agent" class="hover:text-white transition">Agent</a>
                <a href="#accuracy" class="hover:text-white transition">Accuracy</a>
            </div>
        </div>
    </nav>

    <!-- Hero Section -->
    <header class="relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-br from-brand-900/20 via-slate-950 to-purple-900/10"></div>
        <div class="relative max-w-7xl mx-auto px-6 py-16">
            <p class="text-brand-400 font-medium text-sm tracking-wide uppercase mb-3">AI Product Ops Take-Home</p>
            <h1 class="text-4xl md:text-5xl font-bold text-white mb-4 leading-tight">
                100 Apps Analyzed by AI Agent
            </h1>
            <p class="text-slate-400 text-lg max-w-2xl mb-10">
                An automated research pipeline investigating auth methods, API surfaces,
                access models, and agent-toolkit buildability across 100 SaaS apps for Composio.
            </p>

            <!-- Hero Stats -->
            <div id="findings" class="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div class="stat-card glass-card rounded-xl p-5 animate-fade-in animate-delay-1">
                    <div class="text-3xl font-bold text-white">{kwargs['total']}</div>
                    <div class="text-sm text-slate-400 mt-1">Apps Researched</div>
                </div>
                <div class="stat-card glass-card rounded-xl p-5 animate-fade-in animate-delay-2">
                    <div class="text-3xl font-bold text-emerald-400">{kwargs['easy_count']}</div>
                    <div class="text-sm text-slate-400 mt-1">Easy Wins</div>
                </div>
                <div class="stat-card glass-card rounded-xl p-5 animate-fade-in animate-delay-3">
                    <div class="text-3xl font-bold text-brand-400">{kwargs['top_auth_pct']}%</div>
                    <div class="text-sm text-slate-400 mt-1">{kwargs['top_auth']}</div>
                </div>
                <div class="stat-card glass-card rounded-xl p-5 animate-fade-in animate-delay-4">
                    <div class="text-3xl font-bold text-purple-400">{kwargs['mcp_count']}</div>
                    <div class="text-sm text-slate-400 mt-1">Have MCP</div>
                </div>
                <div class="stat-card glass-card rounded-xl p-5 animate-fade-in animate-delay-5">
                    <div class="text-3xl font-bold text-amber-400">{kwargs['final_acc']}%</div>
                    <div class="text-sm text-slate-400 mt-1">Verified Accuracy</div>
                </div>
            </div>
        </div>
    </header>

    <!-- Pattern Insights Section -->
    <section id="patterns" class="max-w-7xl mx-auto px-6 py-12">
        <h2 class="text-2xl font-bold text-white mb-2">Key Patterns & Insights</h2>
        <p class="text-slate-400 mb-8">Non-obvious findings from analyzing 100 apps — each with implications for Composio's roadmap.</p>
        <div id="insights-grid" class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- Populated by JS -->
        </div>
    </section>

    <!-- Charts Row -->
    <section class="max-w-7xl mx-auto px-6 py-12">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="glass-card rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Auth Distribution</h3>
                <canvas id="authChart" height="250"></canvas>
            </div>
            <div class="glass-card rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Access Tiers</h3>
                <canvas id="accessChart" height="250"></canvas>
            </div>
            <div class="glass-card rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Buildability</h3>
                <canvas id="buildChart" height="250"></canvas>
            </div>
        </div>
    </section>

    <!-- Strategic 2x2 Matrix -->
    <section id="matrix" class="max-w-7xl mx-auto px-6 py-12">
        <h2 class="text-2xl font-bold text-white mb-2">Strategic Prioritization Matrix</h2>
        <p class="text-slate-400 mb-8">Self-serve access × API breadth — the framework for deciding what to build next.</p>
        <div class="glass-card rounded-xl p-8">
            <div id="quadrant-matrix" class="grid grid-cols-2 gap-1 min-h-[400px]">
                <!-- Populated by JS -->
            </div>
        </div>
    </section>

    <!-- Full Data Table -->
    <section id="data" class="max-w-7xl mx-auto px-6 py-12">
        <h2 class="text-2xl font-bold text-white mb-2">Full Research Data</h2>
        <p class="text-slate-400 mb-6">Click any row to expand full details and evidence URLs.</p>

        <!-- Filters -->
        <div class="flex flex-wrap gap-3 mb-6">
            <input id="searchInput" type="text" placeholder="Search apps..."
                class="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 w-64">
            <select id="categoryFilter" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                <option value="">All Categories</option>
            </select>
            <select id="authFilter" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                <option value="">All Auth</option>
            </select>
            <select id="buildFilter" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                <option value="">All Buildability</option>
                <option value="easy">🟢 Easy</option>
                <option value="moderate">🟡 Moderate</option>
                <option value="hard">🟠 Hard</option>
                <option value="not_feasible">🔴 Not Feasible</option>
            </select>
        </div>

        <!-- Table -->
        <div class="glass-card rounded-xl overflow-hidden">
            <div class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead>
                        <tr class="border-b border-slate-700 text-slate-400 text-left">
                            <th class="px-4 py-3 font-medium cursor-pointer hover:text-white" onclick="sortTable('id')">#</th>
                            <th class="px-4 py-3 font-medium cursor-pointer hover:text-white" onclick="sortTable('name')">App</th>
                            <th class="px-4 py-3 font-medium cursor-pointer hover:text-white" onclick="sortTable('category')">Category</th>
                            <th class="px-4 py-3 font-medium">Auth</th>
                            <th class="px-4 py-3 font-medium">Access</th>
                            <th class="px-4 py-3 font-medium">API</th>
                            <th class="px-4 py-3 font-medium">MCP</th>
                            <th class="px-4 py-3 font-medium cursor-pointer hover:text-white" onclick="sortTable('buildability')">Build</th>
                        </tr>
                    </thead>
                    <tbody id="appTableBody">
                        <!-- Populated by JS -->
                    </tbody>
                </table>
            </div>
        </div>
    </section>

    <!-- The Agent Section -->
    <section id="agent" class="max-w-7xl mx-auto px-6 py-12">
        <h2 class="text-2xl font-bold text-white mb-2">The Agent: How It Works</h2>
        <p class="text-slate-400 mb-8">Architecture, tooling, and an honest accounting of what worked and what didn't.</p>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- Pipeline -->
            <div class="glass-card rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Pipeline Architecture</h3>
                <div class="space-y-3">
                    <div class="flex items-center gap-3">
                        <span class="w-8 h-8 rounded-lg bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold">1</span>
                        <div><span class="text-white font-medium">Web Research</span><span class="text-slate-400 text-sm ml-2">Firecrawl + direct HTTP, plus a separate GitHub/npm MCP check</span></div>
                    </div>
                    <div class="flex items-center gap-3">
                        <span class="w-8 h-8 rounded-lg bg-purple-500/20 text-purple-400 flex items-center justify-center text-sm font-bold">2</span>
                        <div><span class="text-white font-medium">LLM Classification</span><span class="text-slate-400 text-sm ml-2">Groq (Llama 3.3 / GPT-OSS) with OpenRouter fallback, temp=0</span></div>
                    </div>
                    <div class="flex items-center gap-3">
                        <span class="w-8 h-8 rounded-lg bg-red-500/20 text-red-400 flex items-center justify-center text-sm font-bold">3</span>
                        <div><span class="text-white font-medium">Verification</span><span class="text-slate-400 text-sm ml-2">3-layer: auto (incl. Composio's own catalog) + agent + human</span></div>
                    </div>
                    <div class="flex items-center gap-3">
                        <span class="w-8 h-8 rounded-lg bg-green-500/20 text-green-400 flex items-center justify-center text-sm font-bold">4</span>
                        <div><span class="text-white font-medium">Pattern Analysis</span><span class="text-slate-400 text-sm ml-2">8 dimensions, 8 insights</span></div>
                    </div>
                </div>
            </div>

            <!-- What worked / failed -->
            <div class="glass-card rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Honest Assessment</h3>
                <div class="space-y-4">
                    <div>
                        <h4 class="text-emerald-400 font-medium mb-1">✅ What Worked</h4>
                        <ul class="text-slate-400 text-sm space-y-1">
                            <li>• Firecrawl + direct HTTP covered docs for the large majority of apps</li>
                            <li>• Groq's structured JSON mode reliably extracted data when quota was available</li>
                            <li>• Composio's own toolkit catalog gave real ground truth for 50/100 apps (real tool counts, real auth modes) — a genuine cross-check, not just LLM inference</li>
                            <li>• The verification/correction loop caught and auto-fixed real errors, e.g. Stripe was first classified auth=not_found/buildability=not_feasible; independent re-check corrected it to OAuth2/easy</li>
                        </ul>
                    </div>
                    <div>
                        <h4 class="text-amber-400 font-medium mb-1">⚠️ Where Human Was Needed</h4>
                        <ul class="text-slate-400 text-sm space-y-1">
                            <li>• Groq's free daily quota ran out mid-run — wiring an OpenRouter fallback, plus a taxonomy-normalization layer (the free fallback model doesn't reliably honor strict enums), took manual debugging across several retry passes</li>
                            <li>• Two verification-pipeline bugs (a JSON-shape edge case, a None-vs-missing-key edge case) silently deflated/corrupted results mid-run and needed a human to catch and fix</li>
                            <li>• Gated apps (PitchBook, DealCloud, Brex) needed judgment calls on "is this really self-serve" beyond what the docs literally say</li>
                            <li>• Human spot-check checklist generated for 12 apps across all 10 categories for manual doc cross-referencing (data/verification/human_checklist.md)</li>
                        </ul>
                    </div>
                    <div>
                        <h4 class="text-red-400 font-medium mb-1">❌ What Failed</h4>
                        <ul class="text-slate-400 text-sm space-y-1">
                            <li>• fanbasis, iPayX: no usable public API docs found — low-confidence, best-effort classification</li>
                            <li>• The free OpenRouter fallback model occasionally returned garbled/repeated-token output under load, requiring a second classification pass for a handful of apps</li>
                            <li>• Sherlock, Mermaid CLI are CLI tools, not SaaS APIs — correctly flagged CLI_Only but with inherently thin "API surface" data</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- Verification & Accuracy Section -->
    <section id="accuracy" class="max-w-7xl mx-auto px-6 py-12">
        <h2 class="text-2xl font-bold text-white mb-2">Verification & Accuracy</h2>
        <p class="text-slate-400 mb-8">Three-layer verification with documented accuracy improvement.</p>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            <!-- Accuracy improvement -->
            <div class="glass-card rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Accuracy Improvement</h3>
                <canvas id="accuracyChart" height="200"></canvas>
                <div class="mt-4 text-center">
                    <span class="text-slate-400 text-sm">First Pass</span>
                    <span class="text-2xl font-bold text-amber-400 mx-3">{kwargs['first_pass_acc']}%</span>
                    <span class="text-slate-500">→</span>
                    <span class="text-2xl font-bold text-emerald-400 mx-3">{kwargs['final_acc']}%</span>
                    <span class="text-slate-400 text-sm">Final</span>
                </div>
            </div>

            <!-- Per-field accuracy -->
            <div class="glass-card rounded-xl p-6">
                <h3 class="text-lg font-semibold text-white mb-4">Per-Field Accuracy</h3>
                <div id="fieldAccuracy" class="space-y-3">
                    <!-- Populated by JS -->
                </div>
            </div>
        </div>

        <!-- Methodology -->
        <div class="glass-card rounded-xl p-6">
            <h3 class="text-lg font-semibold text-white mb-3">Methodology</h3>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm text-slate-400">
                <div>
                    <span class="text-white font-medium">Layer 1: Automated</span>
                    <p class="mt-1">Logical consistency checks + known-good ground truth + evidence URL validation across all 100 apps.</p>
                </div>
                <div>
                    <span class="text-white font-medium">Layer 2: Verification Agent</span>
                    <p class="mt-1">Independent LLM call with fresh docs and different prompt angle on 25 random + flagged apps.</p>
                </div>
                <div>
                    <span class="text-white font-medium">Layer 3: Human Check</span>
                    <p class="mt-1">Manual browser verification of 10-15 apps (1+ per category) with documented evidence.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- Footer -->
    <footer class="border-t border-slate-800 mt-12">
        <div class="max-w-7xl mx-auto px-6 py-8 flex flex-col md:flex-row items-center justify-between text-sm text-slate-500">
            <div>Built by <span class="text-white">Satyabrata Mohanty</span> · AI Product Ops Take-Home · July 2026</div>
            <div class="flex gap-4 mt-3 md:mt-0">
                <a href="https://github.com/Satya900/composio-app-research" class="hover:text-white transition">GitHub Repo</a>
                <span>·</span>
                <span>Powered by Composio SDK (toolkit catalog) + Firecrawl + Groq/OpenRouter</span>
            </div>
        </div>
    </footer>

    <!-- JavaScript: Data Rendering -->
    <script>
    document.addEventListener('DOMContentLoaded', () => {{
        renderInsights();
        renderTable();
        renderCharts();
        renderQuadrant();
        renderFieldAccuracy();
        initFilters();
    }});

    // ─── Insights ───────────────────────────────────────────────────────
    function renderInsights() {{
        const grid = document.getElementById('insights-grid');
        if (!PATTERNS.insights) return;

        const categoryIcons = {{
            auth: '🔐', access: '🚪', buildability: '🏗️',
            blockers: '🚧', mcp: '🔌', strategy: '🎯'
        }};

        grid.innerHTML = PATTERNS.insights.map((insight, i) => `
            <div class="glass-card rounded-xl p-5 hover:border-brand-500/50 transition-colors">
                <div class="flex items-start gap-3">
                    <span class="text-2xl">${{categoryIcons[insight.category] || '📊'}}</span>
                    <div>
                        <h3 class="text-white font-semibold text-sm leading-snug mb-2">${{insight.headline}}</h3>
                        <p class="text-slate-400 text-xs leading-relaxed">${{insight.implication}}</p>
                    </div>
                </div>
            </div>
        `).join('');
    }}

    // ─── Table ──────────────────────────────────────────────────────────
    let currentSort = {{ field: 'id', asc: true }};

    function renderTable(filtered) {{
        const data = filtered || RESULTS;
        const tbody = document.getElementById('appTableBody');

        const badgeClass = {{ easy: 'badge-easy', moderate: 'badge-moderate', hard: 'badge-hard', not_feasible: 'badge-not_feasible' }};
        const badgeEmoji = {{ easy: '🟢', moderate: '🟡', hard: '🟠', not_feasible: '🔴' }};

        tbody.innerHTML = data.map(app => `
            <tr class="app-row border-b border-slate-800/50 cursor-pointer" onclick="toggleDetail(${{app.id}})">
                <td class="px-4 py-3 text-slate-500">${{app.id}}</td>
                <td class="px-4 py-3 text-white font-medium">${{app.name}}</td>
                <td class="px-4 py-3 text-slate-400 text-xs">${{app.category}}</td>
                <td class="px-4 py-3"><span class="text-xs px-2 py-1 rounded bg-slate-800">${{app.auth_primary || 'N/A'}}</span></td>
                <td class="px-4 py-3 text-xs">${{app.self_serve ? '<span class="text-emerald-400">Self-serve</span>' : '<span class="text-amber-400">Gated</span>'}}</td>
                <td class="px-4 py-3 text-xs text-slate-400">${{(app.api_type || []).join(', ') || 'N/A'}}</td>
                <td class="px-4 py-3">${{app.composio_toolkit_exists ? `🧩 ${{app.composio_tools_count ?? ''}}` : (app.has_existing_mcp ? '✅' : '—')}}</td>
                <td class="px-4 py-3"><span class="text-xs px-2 py-1 rounded ${{badgeClass[app.buildability] || ''}}">${{badgeEmoji[app.buildability] || ''}} ${{app.buildability || 'N/A'}}</span></td>
            </tr>
            <tr id="detail-${{app.id}}" class="hidden">
                <td colspan="8" class="px-6 py-4 bg-slate-900/50">
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                        <div><span class="text-slate-500">One-liner:</span> <span class="text-slate-300">${{app.one_liner || 'N/A'}}</span></div>
                        <div><span class="text-slate-500">Auth Methods:</span> <span class="text-slate-300">${{(app.auth_methods || []).join(', ')}}</span></div>
                        <div><span class="text-slate-500">Access Tier:</span> <span class="text-slate-300">${{app.access_tier || 'N/A'}}</span></div>
                        <div><span class="text-slate-500">API Breadth:</span> <span class="text-slate-300">${{app.api_breadth || 'N/A'}}</span></div>
                        <div><span class="text-slate-500">Docs Quality:</span> <span class="text-slate-300">${{app.api_docs_quality || 'N/A'}}</span></div>
                        <div><span class="text-slate-500">Has SDK:</span> <span class="text-slate-300">${{app.has_sdk ? 'Yes' : 'No'}} ${{(app.sdk_languages || []).length ? '(' + app.sdk_languages.join(', ') + ')' : ''}}</span></div>
                        <div><span class="text-slate-500">Webhooks:</span> <span class="text-slate-300">${{app.has_webhooks ? 'Yes' : 'No'}}</span></div>
                        <div><span class="text-slate-500">Confidence:</span> <span class="text-slate-300">${{app.confidence || 'N/A'}}</span></div>
                        <div><span class="text-slate-500">Composio Toolkit:</span> <span class="text-slate-300">${{app.composio_toolkit_exists ? `Yes — ${{app.composio_tools_count}} tools (Composio catalog)` : 'Not yet built'}}</span></div>
                    </div>
                    <div class="mt-3 text-xs">
                        <span class="text-slate-500">Buildability Rationale:</span>
                        <span class="text-slate-300"> ${{app.buildability_rationale || 'N/A'}}</span>
                    </div>
                    ${{app.main_blocker ? `<div class="mt-1 text-xs"><span class="text-slate-500">Main Blocker:</span> <span class="text-red-400">${{app.main_blocker}}</span></div>` : ''}}
                    ${{(app.evidence_urls || []).length ? `<div class="mt-2 text-xs"><span class="text-slate-500">Evidence:</span> ${{app.evidence_urls.map(u => `<a href="${{u}}" target="_blank" class="text-brand-400 hover:underline ml-1">${{new URL(u).hostname}}</a>`).join(', ')}}</div>` : ''}}
                </td>
            </tr>
        `).join('');
    }}

    function toggleDetail(id) {{
        const row = document.getElementById(`detail-${{id}}`);
        row.classList.toggle('hidden');
    }}

    function sortTable(field) {{
        currentSort.asc = currentSort.field === field ? !currentSort.asc : true;
        currentSort.field = field;
        const sorted = [...RESULTS].sort((a, b) => {{
            const va = a[field], vb = b[field];
            const cmp = typeof va === 'string' ? va.localeCompare(vb) : va - vb;
            return currentSort.asc ? cmp : -cmp;
        }});
        renderTable(sorted);
    }}

    // ─── Filters ────────────────────────────────────────────────────────
    function initFilters() {{
        const categories = [...new Set(RESULTS.map(r => r.category))].sort();
        const auths = [...new Set(RESULTS.map(r => r.auth_primary).filter(Boolean))].sort();

        const catSelect = document.getElementById('categoryFilter');
        categories.forEach(c => {{ catSelect.innerHTML += `<option value="${{c}}">${{c}}</option>`; }});

        const authSelect = document.getElementById('authFilter');
        auths.forEach(a => {{ authSelect.innerHTML += `<option value="${{a}}">${{a}}</option>`; }});

        // Bind filter events
        ['searchInput', 'categoryFilter', 'authFilter', 'buildFilter'].forEach(id => {{
            document.getElementById(id).addEventListener(id === 'searchInput' ? 'input' : 'change', applyFilters);
        }});
    }}

    function applyFilters() {{
        const search = document.getElementById('searchInput').value.toLowerCase();
        const cat = document.getElementById('categoryFilter').value;
        const auth = document.getElementById('authFilter').value;
        const build = document.getElementById('buildFilter').value;

        const filtered = RESULTS.filter(r => {{
            if (search && !r.name.toLowerCase().includes(search)) return false;
            if (cat && r.category !== cat) return false;
            if (auth && r.auth_primary !== auth) return false;
            if (build && r.buildability !== build) return false;
            return true;
        }});

        renderTable(filtered);
    }}

    // ─── Charts ─────────────────────────────────────────────────────────
    function renderCharts() {{
        const chartColors = ['#5c7cfa', '#a855f7', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6'];

        // Auth Distribution (Doughnut)
        if (PATTERNS.auth_distribution) {{
            const labels = Object.keys(PATTERNS.auth_distribution);
            const data = Object.values(PATTERNS.auth_distribution);
            new Chart(document.getElementById('authChart'), {{
                type: 'doughnut',
                data: {{
                    labels, datasets: [{{ data, backgroundColor: chartColors.slice(0, labels.length), borderWidth: 0 }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{
                        legend: {{ position: 'bottom', labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
                    }}
                }}
            }});
        }}

        // Access Distribution (Bar)
        if (PATTERNS.access_distribution) {{
            const labels = Object.keys(PATTERNS.access_distribution).map(l => l.replace('_', ' '));
            const data = Object.values(PATTERNS.access_distribution);
            new Chart(document.getElementById('accessChart'), {{
                type: 'bar',
                data: {{
                    labels, datasets: [{{ data, backgroundColor: '#5c7cfa80', borderColor: '#5c7cfa', borderWidth: 1 }}]
                }},
                options: {{
                    responsive: true, indexAxis: 'y',
                    scales: {{ x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}, y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ display: false }} }} }},
                    plugins: {{ legend: {{ display: false }} }}
                }}
            }});
        }}

        // Buildability (Doughnut)
        const buildCounts = {{ easy: 0, moderate: 0, hard: 0, not_feasible: 0 }};
        RESULTS.forEach(r => {{ if (buildCounts[r.buildability] !== undefined) buildCounts[r.buildability]++; }});
        new Chart(document.getElementById('buildChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['Easy', 'Moderate', 'Hard', 'Not Feasible'],
                datasets: [{{ data: Object.values(buildCounts), backgroundColor: ['#22c55e', '#f59e0b', '#f97316', '#ef4444'], borderWidth: 0 }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }} }}
            }}
        }});

        // Accuracy improvement
        if (ACCURACY.first_pass_accuracy !== undefined) {{
            new Chart(document.getElementById('accuracyChart'), {{
                type: 'bar',
                data: {{
                    labels: ['First Pass', 'After Verification'],
                    datasets: [{{ data: [ACCURACY.first_pass_accuracy, ACCURACY.final_accuracy], backgroundColor: ['#f59e0b80', '#22c55e80'], borderColor: ['#f59e0b', '#22c55e'], borderWidth: 2 }}]
                }},
                options: {{
                    responsive: true,
                    scales: {{ y: {{ min: 0, max: 100, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}, x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ display: false }} }} }},
                    plugins: {{ legend: {{ display: false }} }}
                }}
            }});
        }}
    }}

    // ─── Quadrant Matrix ────────────────────────────────────────────────
    function renderQuadrant() {{
        const container = document.getElementById('quadrant-matrix');
        if (!PATTERNS.insights) return;

        const strategyInsight = PATTERNS.insights.find(i => i.category === 'strategy');
        const quadrants = strategyInsight?.supporting_data || {{}};

        const cells = [
            {{ key: 'easy_wins', label: '🟢 Easy Wins', subtitle: 'Self-serve + Broad API', bg: 'bg-emerald-500/5 border-emerald-500/20' }},
            {{ key: 'quick_builds', label: '🟡 Quick Builds', subtitle: 'Self-serve + Narrow API', bg: 'bg-amber-500/5 border-amber-500/20' }},
            {{ key: 'worth_outreach', label: '🟠 Worth Outreach', subtitle: 'Gated + Broad API', bg: 'bg-orange-500/5 border-orange-500/20' }},
            {{ key: 'deprioritize', label: '🔴 Deprioritize', subtitle: 'Gated + Narrow API', bg: 'bg-red-500/5 border-red-500/20' }},
        ];

        container.innerHTML = cells.map(cell => `
            <div class="rounded-lg border ${{cell.bg}} p-4">
                <div class="font-semibold text-white text-sm mb-1">${{cell.label}} (${{(quadrants[cell.key] || []).length}})</div>
                <div class="text-slate-500 text-xs mb-3">${{cell.subtitle}}</div>
                <div class="flex flex-wrap gap-1">
                    ${{(quadrants[cell.key] || []).map(app => `<span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300">${{app}}</span>`).join('')}}
                </div>
            </div>
        `).join('');

        // Add axis labels
        container.insertAdjacentHTML('beforebegin',
            '<div class="flex justify-between text-xs text-slate-500 mb-2"><span>← Broad API</span><span>Narrow API →</span></div>'
        );
        container.insertAdjacentHTML('afterend',
            '<div class="flex justify-between text-xs text-slate-500 mt-2"><span>↑ Self-serve</span><span>↓ Gated</span></div>'
        );
    }}

    // ─── Per-Field Accuracy ─────────────────────────────────────────────
    function renderFieldAccuracy() {{
        const container = document.getElementById('fieldAccuracy');
        if (!ACCURACY.per_field_accuracy) return;

        const fields = Object.entries(ACCURACY.per_field_accuracy);
        container.innerHTML = fields.map(([field, pct]) => {{
            const color = pct >= 90 ? 'bg-emerald-500' : pct >= 80 ? 'bg-amber-500' : 'bg-red-500';
            return `
                <div>
                    <div class="flex justify-between text-xs mb-1">
                        <span class="text-slate-400">${{field.replace('_', ' ')}}</span>
                        <span class="text-white font-medium">${{pct}}%</span>
                    </div>
                    <div class="w-full bg-slate-800 rounded-full h-2">
                        <div class="${{color}} h-2 rounded-full transition-all" style="width: ${{pct}}%"></div>
                    </div>
                </div>
            `;
        }}).join('');
    }}
    </script>
</body>
</html>"""
