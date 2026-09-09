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


def test_tutorial_information_architecture_is_casual_first_and_glossary_first():
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


def test_glossary_is_searchable_expandable_alphabetical_and_alias_aware():
    js = _education()
    assert "type=\"search\"" in js
    assert "Search EV, juice, PT, spread" in js
    assert "function filterGlossary" in js
    assert "entry.dataset.search.includes(q)" in js
    assert "GLOSSARY.slice().sort((a,b)=>a.term.localeCompare(b.term))" in js
    assert "<details class=\"glossary-entry\"" in js
    assert "aliases:['ev','expected value']" in js
    assert "aliases:['juice','vig','vigorish','sportsbook margin']" in js
    assert "aliases:['pt','play-through','play thru']" in js


def test_required_user_facing_terms_have_definitions():
    js = _education()
    required = [
        "Model",
        "Machine Learning",
        "No Gut Check / Human Override",
        "Probability",
        "Break-even Probability",
        "Expected Value (EV)",
        "Hit Rate",
        "Balanced",
        "Value",
        "Trust Probability",
        "Reliability",
        "Confidence / Model Confidence",
        "Moneyline",
        "Spread",
        "Over / Under / Total",
        "American Odds / Price",
        "Juice / Vig",
        "Line",
        "Price vs Line",
        "Exact Offer",
        "Play Through",
        "Value At",
        "Units",
        "Bankroll",
        "Risk Profile",
        "BET",
        "BET (CAPPED)",
        "NO PLAY",
        "TARGET ONLY / Watch Price",
        "Suppressed",
        "Unsupported",
        "Favorite",
        "Underdog",
        "Push",
        "Sportsbook",
        "Pinnacle",
        "Market",
        "Market Comparison Colors",
        "Fresh",
        "Aging",
        "Stale",
        "Model Details",
        "Roof Sensitive",
        "ROI",
        "Selection",
        "Recommended Stake",
        "Playable Price",
        "Value Price",
        "Outside Range",
        "Evaluator Result",
        "Market Probability",
        "Trust Coverage / Trust Fallback",
        "Wager Logged / Open / Settled",
        "Check / Exact-Offer Check",
    ]
    missing = [term for term in required if f"term:'{term}'" not in js]
    assert not missing, missing


def test_plain_language_preserves_actual_product_semantics():
    js = _education()
    must_have = [
        "Hit Rate ≠ Profit Rate",
        "-198 is worse and outside",
        "For an Over, a lower total is better; for an Under, a higher total is better",
        "HIGH, MEDIUM, LOW, or UNSUPPORTED",
        "strictly-prior support, uncertainty, stability, model disagreement",
        "not the probability that today’s wager is correct",
        "pull model strength partway toward the Pinnacle benchmark",
        "same sportsbook, selection, line, and price",
        "The bet became worse",
        "A BET can lose",
        "It does not mean “bad bet.”",
        "does not place the wager",
    ]
    for phrase in must_have:
        assert phrase in js


def test_quick_start_common_mistakes_and_before_bet_checklist_exist():
    js = _education()
    for phrase in [
        "Set your bankroll and risk level",
        "Start on the Board",
        "Look for BET",
        "Check the exact sportsbook offer",
        "Respect Play Through and Value At",
        "Log the wager",
        "Check back later",
        "Chasing past Play Through",
        "Treating Value as “most likely winner”",
        "Doubling a duplicate",
        "Inflating bankroll to get a bigger bet",
        "Reading BET as guaranteed",
        "Reading NO PLAY as “the model hates them”",
        "Ignoring the sportsbook",
        "Is the recommendation still <strong>BET</strong>?",
        "Has important QB, injury, or roof information changed?",
    ]:
        assert phrase in js


def test_model_education_has_no_gut_override_and_no_guarantee_language():
    js = _education()
    assert "Math first. No gut-pick override." in js
    assert "does not add a last-minute human" in js
    assert "Machine learning finds patterns in historical data" in js
    assert "does not see the future" in js
    assert "QB-Elo" in js
    assert "XGBoost V2" in js
    assert "Expected Margin V1 Stable" in js
    assert "Ridge Totals R4" in js
    assert "Even a true 70% event loses about 30% of the time" in js
    assert "A promise of profit" in js
    assert "News" not in js


def test_theme_mobile_and_accessibility_contracts_are_native():
    js = _education()
    for css_var in [
        "var(--bg)",
        "var(--surface)",
        "var(--surface-2)",
        "var(--ink)",
        "var(--ink-2)",
        "var(--ink-3)",
        "var(--line)",
        "var(--edge-blue)",
        "var(--action-bet)",
        "var(--ribbon-hhr)",
        "var(--ribbon-balanced)",
        "var(--ribbon-value)",
    ]:
        assert css_var in js
    assert "width:min(100vw,480px)" in js
    assert "height:100dvh" in js
    assert "overflow-x:hidden" in js
    assert "@media(max-width:360px)" in js
    assert "min-height:44px" in js
    assert "aria-labelledby" in js
    assert "aria-label=\"Tutorial sections\"" in js
    assert "aria-label=\"Close tutorial\"" in js
    assert "prefers-reduced-motion:reduce" in js
    assert "window.addEventListener('popstate'" in js
    assert "dialog.addEventListener('cancel'" in js


def test_education_is_static_presentation_only_and_does_not_reimplement_product_math():
    js = _education()
    forbidden = [
        "/api/v1/",
        "fetch(",
        "ApiClient",
        "americanToImplied",
        "stakeFromUnits",
        "unitDollars",
        "ODDS_API_KEY",
        "api.the-odds-api.com",
        "RELIABILITY_HAIRCUT",
        "PT_CONCESSION_PP",
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
