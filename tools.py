import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "seed_data.json")

def _load_data() -> dict:
    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"seed_data.json not found at {_DATA_PATH}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"seed_data.json is malformed: {e}")

DATA = _load_data()


def hot_picks(state: str, budget: float, limit: int = 5) -> list[dict]:
    try:
        results = []
        for product in DATA["products"]:
            if state in product.get("blocked_states", []):
                continue
            if product["price"] > budget:
                continue
            results.append({
                "product_id":       product["product_id"],
                "sku":              product["sku"],
                "name":             product["name"],
                "category":         product["category"],
                "price":            product["price"],
                "popularity_score": product["popularity_score"]
            })
        results.sort(key=lambda x: x["popularity_score"], reverse=True)
        return results[:limit]
    except Exception as e:
        raise RuntimeError(f"hot_picks failed: {e}")


def compliance_filter(state: str, product_ids: list[str]) -> dict:
    try:
        product_map = {}
        for p in DATA["products"]:
            product_map[p["product_id"]] = p
            product_map[p["sku"]]        = p

        allowed, blocked, review = [], [], []

        for pid in product_ids:
            product = product_map.get(pid)
            if not product:
                blocked.append({"product_id": pid, "reason_code": "PRODUCT_NOT_FOUND"})
                continue

            if state in product.get("blocked_states", []):
                blocked.append({
                    "product_id":  pid,
                    "sku":         product["sku"],
                    "name":        product["name"],
                    "reason_code": f"BLOCKED_IN_{state}",
                    "flags":       product.get("flags", [])
                })
            elif product.get("lab_report_required"):
                review.append({
                    "product_id":  pid,
                    "sku":         product["sku"],
                    "name":        product["name"],
                    "reason_code": "LAB_REPORT_REQUIRED",
                    "flags":       product.get("flags", [])
                })
            else:
                allowed.append({
                    "product_id":  pid,
                    "sku":         product["sku"],
                    "name":        product["name"],
                    "reason_code": "ALLOWED",
                    "flags":       product.get("flags", [])
                })

        alternatives = []
        if blocked:
            for product in DATA["products"]:
                if state not in product.get("blocked_states", []) and \
                   product["product_id"] not in product_ids:
                    alternatives.append({
                        "product_id":       product["product_id"],
                        "sku":              product["sku"],
                        "name":             product["name"],
                        "category":         product["category"],
                        "popularity_score": product["popularity_score"]
                    })
            alternatives.sort(key=lambda x: x["popularity_score"], reverse=True)
            alternatives = alternatives[:3]

        return {
            "state":        state,
            "allowed":      allowed,
            "blocked":      blocked,
            "review":       review,
            "alternatives": alternatives
        }
    except Exception as e:
        raise RuntimeError(f"compliance_filter failed: {e}")


def stock_by_warehouse(product_id: str) -> dict:
    try:
        product = next(
            (p for p in DATA["products"] if p["product_id"] == product_id or p["sku"] == product_id),
            None
        )
        if not product:
            return {"product_id": product_id, "error": "PRODUCT_NOT_FOUND", "warehouses": [], "total_qty": 0}

        warehouses = [
            {"warehouse": row["warehouse"], "qty": row["qty"]}
            for row in DATA["inventory"]
            if row["product_id"] == product["product_id"]
        ]
        total_qty = sum(w["qty"] for w in warehouses)

        return {
            "product_id": product["product_id"],
            "sku":        product["sku"],
            "name":       product["name"],
            "warehouses": warehouses,
            "total_qty":  total_qty
        }
    except Exception as e:
        raise RuntimeError(f"stock_by_warehouse failed: {e}")


def vendor_validate(attributes: dict) -> dict:
    try:
        REQUIRED_FIELDS = ["name", "category", "net_wt_oz", "net_vol_ml"]
        REQUIRED_DOCS_BY_CATEGORY = {
            "THC Edible":     ["lab_report", "coa", "business_license"],
            "THC Beverage":   ["lab_report", "coa", "business_license", "fda_registration"],
            "CBD":            ["lab_report", "coa", "business_license"],
            "Delta-8":        ["lab_report", "coa", "business_license"],
            "Nicotine Vape":  ["business_license", "msds"],
            "Nicotine Pouch": ["business_license", "msds"],
            "Hemp":           ["lab_report", "coa", "business_license"],
            "Caffeine Vape":  ["business_license", "msds"]
        }

        missing_fields, missing_docs, issues = [], [], []

        for field in REQUIRED_FIELDS:
            val = attributes.get(field)
            if val is None or val == "" or val == 0:
                missing_fields.append(field)

        has_weight = attributes.get("net_wt_oz") not in [None, 0, ""]
        has_volume = attributes.get("net_vol_ml") not in [None, 0, ""]
        if not has_weight and not has_volume:
            issues.append("At least one of net_wt_oz or net_vol_ml is required")

        category     = attributes.get("category", "")
        required_docs = REQUIRED_DOCS_BY_CATEGORY.get(category, ["business_license"])

        if "lab_report" in required_docs and not attributes.get("lab_report_attached"):
            missing_docs.append("lab_report")
        if "fda_registration" in required_docs and not attributes.get("fda_registration_attached"):
            missing_docs.append("fda_registration")

        nicotine_mg = attributes.get("nicotine_mg", 0)
        if nicotine_mg and nicotine_mg > 0 and "nicotine" not in category.lower():
            issues.append(f"nicotine_mg={nicotine_mg} declared but category is {category}")

        if missing_docs or (missing_fields and "net_wt_oz" in missing_fields and not has_volume):
            status = "FAIL"
        elif missing_fields or issues:
            status = "REVIEW"
        else:
            status = "PASS"

        return {
            "status":             status,
            "missing_fields":     missing_fields,
            "missing_documents":  missing_docs,
            "required_documents": required_docs,
            "issues":             issues,
            "category":           category,
            "checklist":          {field: field not in missing_fields for field in REQUIRED_FIELDS}
        }
    except Exception as e:
        raise RuntimeError(f"vendor_validate failed: {e}")


def kb_search(query: str, top_k: int = 2, user_visibility: str = "internal") -> list[dict]:
    try:
        VISIBILITY_MAP = {
            "internal":        ["internal", "portal_customer", "portal_vendor"],
            "portal_customer": ["portal_customer"],
            "portal_vendor":   ["portal_vendor"],
        }
        allowed_visibility = VISIBILITY_MAP.get(user_visibility, ["portal_customer"])
        query_words = set(query.lower().split())

        scored = []
        for doc in DATA["kb_docs"]:
            if doc["visibility"] not in allowed_visibility:
                continue
            doc_words = set((doc["title"] + " " + doc["text"]).lower().split())
            score = len(query_words & doc_words)
            if score > 0:
                scored.append({
                    "doc_id":  doc["doc_id"],
                    "title":   doc["title"],
                    "snippet": doc["text"][:300] + "..." if len(doc["text"]) > 300 else doc["text"],
                    "score":   score
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]
    except Exception as e:
        raise RuntimeError(f"kb_search failed: {e}")
