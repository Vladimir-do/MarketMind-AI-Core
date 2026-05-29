import json
import os
import urllib.error
import urllib.parse
import urllib.request


WB_CARD_URL = os.getenv(
    "WB_CARD_URL",
    "https://card.wb.ru/cards/v2/detail",
)
PRODUCT_ID_KEYS = ("product_id", "id", "nm", "nm_id", "nmId")
WB_API_URLS = (
    "https://card.wb.ru/cards/v2/detail",
    "https://card.wb.ru/cards/detail",
    "https://card.wb.ru/cards/v1/detail",
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
    "Priority": "u=1, i",
}


def handler(event, context):
    try:
        product_id = _get_product_id(event)
        if not product_id:
            return _response(400, {
                "error": "product_id is required",
                "accepted_keys": list(PRODUCT_ID_KEYS),
            })

        payload = _fetch_wb_card(product_id)
        products = payload.get("data", {}).get("products") or payload.get("products") or []
        if not products:
            return _response(404, {
                "error": "product not found",
                "product_id": product_id,
                "wb_response": payload,
            })
        return _response(200, payload)
    except urllib.error.HTTPError as e:
        return _response(e.code, {"error": e.reason})
    except Exception as e:
        return _response(500, {"error": str(e)})


def _get_product_id(event):
    if not isinstance(event, dict):
        return None

    for container_key in ("queryStringParameters", "multiValueQueryStringParameters", "pathParameters", "params"):
        params = event.get(container_key) or {}
        product_id = _get_from_mapping(params)
        if product_id:
            return product_id

    product_id = _get_from_mapping(event)
    if product_id:
        return product_id

    body = event.get("body")
    if not body:
        return None

    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    if isinstance(body, str):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = urllib.parse.parse_qs(body)
    elif isinstance(body, dict):
        data = body
    else:
        return None

    return _get_from_mapping(data)


def _get_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return None
    for key in PRODUCT_ID_KEYS:
        value = mapping.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            return str(value).strip()
    return None


def _fetch_wb_card(product_id):
    query = urllib.parse.urlencode({
        "appType": 1,
        "curr": "rub",
        "dest": -1257786,
        "spp": 30,
        "nm": product_id,
    })
    errors = []
    for base_url in _wb_api_urls():
        url = f"{base_url}?{query}"
        request = urllib.request.Request(
            url,
            headers=HEADERS,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            errors.append({"url": url, "status": e.code, "reason": e.reason})
            continue

        products = payload.get("data", {}).get("products") or payload.get("products") or []
        if products:
            payload["_source_url"] = url
            return payload
        errors.append({"url": url, "status": 200, "reason": "empty products"})

    return {"data": {"products": []}, "errors": errors}


def _wb_api_urls():
    urls = [WB_CARD_URL] if WB_CARD_URL else []
    urls.extend(WB_API_URLS)
    result = []
    for url in urls:
        if url not in result:
            result.append(url)
    return result


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }
