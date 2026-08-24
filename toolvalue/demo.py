from __future__ import annotations

from collections import Counter
from typing import Any

from .profiler import profile
from .instrument import tool
from .store import Store
from .types import EvalCase, ProfileReport, ToolUnavailable

EXTERNAL_CALLS: Counter[str] = Counter()

BUSINESSES = [
    {"name": "Harbor & Finch LLP", "expected": "Legal services", "segment": "professional_services", "homepage": ("Legal services", .96), "about": ("Professional services", .45), "reviews": ("Law firm", .30), "registry": ("Legal services", .75), "search": ("Professional services", .40)},
    {"name": "North Loop Advisory", "expected": "Management consulting", "segment": "professional_services", "homepage": ("Management consulting", .92), "about": ("Business services", .50), "reviews": ("Consulting", .35), "registry": ("Management consulting", .70), "search": ("Business services", .45)},
    {"name": "Casa Juniper", "expected": "Restaurant", "segment": "restaurant", "homepage": ("Hospitality", .70), "about": ("Hospitality", .55), "reviews": ("Restaurant", .98), "registry": ("Food services", .65), "search": ("Restaurant", .60)},
    {"name": "Redbud Table", "expected": "Restaurant", "segment": "restaurant", "homepage": ("Hospitality", .68), "about": ("Dining", .62), "reviews": ("Restaurant", .97), "registry": ("Food services", .62), "search": ("Dining", .55)},
    {"name": "Austin Flow Pros", "expected": "Plumbing", "segment": "trades", "homepage": ("Plumbing", .95), "about": ("Home services", .56), "reviews": ("Contractor", .42), "registry": ("Plumbing", .72), "search": ("Home services", .45)},
    {"name": "Brightwell Electric", "expected": "Electrical contractor", "segment": "trades", "homepage": ("Electrical contractor", .94), "about": ("Field services", .58), "reviews": ("Contractor", .45), "registry": ("Electrical contractor", .72), "search": ("Home services", .46)},
    {"name": "Morrow & Vale Studio", "expected": "Architecture", "segment": "professional_services", "homepage": ("Design studio", .64), "about": ("Architecture", .94), "reviews": ("Designer", .40), "registry": ("Architecture", .68), "search": ("Design services", .53)},
    {"name": "Parkline Supply Co.", "expected": "Industrial supply", "segment": "retail", "homepage": ("Products", .61), "about": ("Distribution", .64), "reviews": ("Retail", .45), "registry": ("Wholesale", .58), "search": ("Industrial supply", .91)},
    {"name": "Northstar Fabrication LLC", "expected": "Industrial manufacturing", "segment": "brand_legal_mismatch", "homepage": ("Retail", .90), "about": ("Consumer products", .72), "reviews": ("Retail", .65), "registry": ("Industrial manufacturing", .96), "search": ("Retail", .75), "brand_conflict": True},
    {"name": "Alloy Systems", "expected": "Industrial manufacturing", "segment": "brand_legal_mismatch", "homepage": ("Software", .88), "about": ("Technology", .70), "reviews": ("Software", .60), "registry": ("Industrial manufacturing", .95), "search": ("Technology", .68), "brand_conflict": True},
    {"name": "Kinship Pediatrics", "expected": "Medical practice", "segment": "professional_services", "homepage": ("Medical practice", .97), "about": ("Healthcare", .72), "reviews": ("Pediatrician", .56), "registry": ("Medical practice", .75), "search": ("Healthcare", .60)},
    {"name": "Rivers & Cole CPAs", "expected": "Accounting", "segment": "professional_services", "homepage": ("Accounting", .96), "about": ("Financial services", .67), "reviews": ("Accountant", .48), "registry": ("Accounting", .78), "search": ("Financial services", .62)},
]


def _source(business: dict[str, Any], key: str) -> dict[str, Any]:
    EXTERNAL_CALLS[key] += 1
    industry, confidence = business[key]
    return {"industry": industry, "confidence": confidence}


@tool(cost=.001, group="search")
async def search(business: dict[str, Any]) -> dict[str, Any]:
    return _source(business, "search")


@tool(cost=.002, group="web")
async def homepage(business: dict[str, Any]) -> dict[str, Any]:
    return _source(business, "homepage")


@tool(cost=.002, group="web")
async def about_page(business: dict[str, Any]) -> dict[str, Any]:
    return _source(business, "about")


@tool(cost=.007, group="reviews")
async def reviews(business: dict[str, Any]) -> dict[str, Any]:
    return _source(business, "reviews")


@tool(cost=.001, group="registry")
async def registry(business: dict[str, Any]) -> dict[str, Any]:
    result = _source(business, "registry")
    result["brand_conflict"] = bool(business.get("brand_conflict"))
    return result


@tool(cost=.014, group="strong_model")
async def strong_model(business: dict[str, Any]) -> dict[str, Any]:
    EXTERNAL_CALLS["strong_model"] += 1
    return {"industry": business["expected"], "confidence": .98, "resolved": bool(business.get("brand_conflict"))}


def accuracy(result: dict[str, Any], expected: str) -> float:
    return 1.0 if result["industry"] == expected else 0.0


def build_demo_agent(store: Store | None = None):
    @profile(task="industry_classification", scorer=accuracy, store=store)
    async def enrich(business: dict[str, Any]) -> dict[str, Any]:
        found = await search(business)
        home = await homepage(business)
        about = await about_page(business)
        review = await reviews(business)
        registered = await registry(business)
        escalated = await strong_model(business)

        if not isinstance(registered, ToolUnavailable) and registered.get("brand_conflict"):
            if not isinstance(escalated, ToolUnavailable):
                return {"industry": escalated["industry"], "source": "strong_model"}
            return {"industry": "Unknown", "source": "conflict_unresolved"}
        if not isinstance(review, ToolUnavailable) and review["industry"] == "Restaurant" and review["confidence"] >= .9:
            return {"industry": "Restaurant", "source": "reviews"}
        if not isinstance(home, ToolUnavailable) and home["confidence"] >= .85:
            return {"industry": home["industry"], "source": "homepage"}
        if not isinstance(about, ToolUnavailable) and about["confidence"] >= .85:
            return {"industry": about["industry"], "source": "about"}
        if not isinstance(found, ToolUnavailable) and found["confidence"] >= .85:
            return {"industry": found["industry"], "source": "search"}
        if not isinstance(registered, ToolUnavailable) and registered["confidence"] >= .7:
            return {"industry": registered["industry"], "source": "registry"}
        return {"industry": "Unknown", "source": "insufficient_evidence"}

    return enrich


async def run_demo(store: Store | None = None) -> ProfileReport:
    EXTERNAL_CALLS.clear()
    agent = build_demo_agent(store)
    cases = [EvalCase(args=(business,), expected=business["expected"], metadata={"segment": business["segment"]}) for business in BUSINESSES]
    return await agent.evaluate(cases)
