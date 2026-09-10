from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def _education() -> str:
    return (FRONTEND / "education.js").read_text()


def test_board_and_account_have_permanent_learning_entry_points():
    js = _education()
    assert "New to NFL EDGE? Learn how it works" in js
    assert "Glossary, betting basics, recommendations &amp; how to use the app" in js
    assert "userStrip.before(entry)" in js
    assert "Help &amp; Learning" in js
    assert ">NFL EDGE Tutorial<" in js
    assert ">Glossary<" in js
    assert "new MutationObserver(makeAccountHelp)" in js


def test_tutorial_information_architecture_is_beginner_first_and_glossary_first():
    js = _education()
    ordered = [
        "['glossary','Glossary']",
        "['quick-start','Quick Start']",
        "['how-it-works','How NFL EDGE Works']",
        "['recommendations','Understanding Recommendations']",
        "['prices-value','Understanding Prices & Value']",
        "['how-to-use','How to Use NFL EDGE']",
        "['common-mistakes','Common Mistakes']",
        "['about-models','About the Models']",
    ]
    positions = [js.index(token) for token in ordered]
    assert positions == sorted(positions)
    assert "What does that mean?" in js
    assert "How do I actually use this?" in js
    assert "Before the “$20 on Dallas” click" in js
    assert "Football-first help for casual bettors" in js
    assert "casual user" not in js.lower()


def test_glossary_is_searchable_expandable_alphabetical_and_alias_aware():
    js = _education()
    assert 'type="search"' in js
    assert "Search EV, juice, PT, spread" in js
    assert "function filterGlossary" in js
    assert "entry.dataset.search.includes(q)" in js
    assert "GLOSSARY.slice().sort((a,b)=>a.term.localeCompare(b.term))" in js
    assert '<details class="glossary-entry"' in js
    assert "aliases:['ev','expected value']" in js
    assert "aliases:['juice','vig','vigorish','sportsbook margin']" in js
    assert "aliases:['pt','play-through','play thru']" in js


def test_required_user_facing_terms_have_definitions():
    js = _education()
    required = [
        "Model", "Machine Learning", "No Gut Check / Human Override", "Probability",
        "Break-even Probability", "Expected Value (EV)", "Hit Rate", "Balanced", "Value",
        "Trust Probability", "Reliability", "Confidence / Model Confidence", "Moneyline", "Spread",
        "Over / Under / Total", "American Odds / Price", "Juice / Vig", "Line", "Price vs Line",
        "Exact Offer", "Play Through", "Value At", "Units", "Bankroll", "Risk Profile", "BET",
        "BET (CAPPED)", "NO PLAY", "TARGET ONLY / Watch Price", "Suppressed", "Unsupported",
        "Favorite", "Underdog", "Push", "Sportsbook", "Pinnacle", "Market",
        "Market Comparison Colors", "Fresh", "Aging", "Stale", "Model Details", "Roof Sensitive",
        "ROI", "Selection", "Recommended Stake", "Playable Price", "Value Price", "Outside Range",
        "Evaluator Result", "Market Probability", "Trust Coverage / Trust Fallback",
        "Wager Logged / Open / Settled", "Check / Exact-Offer Check",
    ]
    missing = [term for term in required if f"term:'{term}'" not in js]
    assert not missing, missing


def test_beginner_copy_uses_concrete_examples_and_preserves_product_semantics():
    js = _education()
    must_have = [
        "Hit Rate ≠ Profit Rate",
        "-198 is too expensive",
        "+3.5, your team starts the bet with 3.5 points",
        "the bet score becomes 3.5-3",
        "If you bet a team at -3.5, your team starts the bet down 3.5 points",
        "It would need to win by 4 or more",
        "HIGH means the app has stronger historical support",
        "pull that number partway back toward the market",
        "The bet became worse",
        "keep your money for a better spot",
        "does not have enough validated information",
        "you still place the actual bet in your sportsbook",
    ]
    for phrase in must_have:
        assert phrase in js


def test_quick_start_common_mistakes_and_before_bet_checklist_are_simple_and_useful():
    js = _education()
    for phrase in [
        "Set your bankroll and risk level",
        "Start on the Board",
        "Look for BET",
        "Match the sportsbook offer",
        "Respect Play Through and Value At",
        "Use the suggested stake",
        "Log the wager",
        "Check back later",
        "Chasing past Play Through",
        "Treating Value as “most likely winner”",
        "Doubling a duplicate",
        "Inflating bankroll to get a bigger bet",
        "Betting every BET bigger than suggested",
        "Ignoring the sportsbook",
        "Is the recommendation still <strong>BET</strong>?",
        "Has important QB, injury, or weather information changed?",
    ]:
        assert phrase in js
    assert "Has important QB, injury, or roof information changed?" not in js


def test_tutorial_emphasizes_bankroll_protection_and_selective_betting_without_hype():
    js = _education()
    assert "help you keep more of your bankroll" in js
    assert "save your money for the spots" in js
    assert "The easiest money to save is money you never needed to risk" in js
    assert "not built to make you bet more" in js
    assert "throw away the bad ones" in js
    assert "No last-minute “BIG SPOT!” override" in js
    assert "guaranteed profit" not in js.lower()
    assert "sure thing" not in js.lower()
    assert "can't lose" not in js.lower()
    assert "News" not in js


def test_theme_mobile_and_accessibility_contracts_are_native():
    js = _education()
    for css_var in [
        "var(--bg)", "var(--surface)", "var(--surface-2)", "var(--ink)", "var(--ink-2)",
        "var(--ink-3)", "var(--line)", "var(--edge-blue)", "var(--action-bet)",
        "var(--ribbon-hhr)", "var(--ribbon-balanced)", "var(--ribbon-value)",
    ]:
        assert css_var in js
    assert "width:min(100vw,480px)" in js
    assert "height:100dvh" in js
    assert "overflow-x:hidden" in js
    assert "@media(max-width:360px)" in js
    assert "min-height:44px" in js
    assert "aria-labelledby" in js
    assert 'aria-label="Tutorial sections"' in js
    assert 'aria-label="Close tutorial"' in js
    assert "prefers-reduced-motion:reduce" in js
    assert "window.addEventListener('popstate'" in js
    assert "dialog.addEventListener('cancel'" in js


def test_education_is_static_presentation_only_and_does_not_reimplement_product_math():
    js = _education()
    forbidden = [
        "/api/v1/", "fetch(", "ApiClient", "americanToImplied", "stakeFromUnits", "unitDollars",
        "ODDS_API_KEY", "api.the-odds-api.com", "RELIABILITY_HAIRCUT", "PT_CONCESSION_PP",
    ]
    for token in forbidden:
        assert token not in js


def test_pwa_shell_loads_and_precaches_education_asset_without_touching_api_policy():
    install = (FRONTEND / "install-affordance.js").read_text()
    sw = (FRONTEND / "sw.js").read_text()
    assert "import './education.js';" in install
    assert "SHELL_REVISION='user-education-tutorial-v1'" in sw
    assert "CACHE_NAME='nfl-edge-shell-v17-education-v1'" in sw
    assert "'./education.js'" in sw
    assert "url.pathname.startsWith('/api/')" in sw
    assert "fetch(request,{cache:'no-store'})" in sw
