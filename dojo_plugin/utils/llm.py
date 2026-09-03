import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class LiteLLMError(RuntimeError):
    def __init__(self, status, detail):
        super().__init__(f"LiteLLM returned HTTP {status}: {detail}")
        self.status = status


class LiteLLMKeyManager:
    def __init__(
        self,
        *,
        base_url,
        master_key,
        user_key_secret,
        budget_limits,
    ):
        if not master_key:
            raise RuntimeError("LITELLM_MASTER_KEY is not set")
        if not user_key_secret:
            raise RuntimeError("LITELLM_USER_KEY_SECRET is not set")

        self.base_url = base_url.rstrip("/")
        self.master_key = master_key
        self.user_key_secret = user_key_secret.encode()
        self.budget_limits = self._validate_budget_limits(budget_limits)

    @staticmethod
    def _validate_budget_limits(budget_limits):
        if not isinstance(budget_limits, list):
            raise RuntimeError("budget_limits must be a list")
        validated = []
        for budget_limit in budget_limits:
            if not isinstance(budget_limit, dict):
                raise RuntimeError("each budget_limits entry must be an object")
            try:
                max_budget = float(budget_limit["max_budget"])
                budget_duration = str(budget_limit["budget_duration"])
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError(
                    "each budget_limits entry needs max_budget and budget_duration"
                ) from error
            if max_budget <= 0 or not budget_duration:
                raise RuntimeError("budget limits need a positive budget and a duration")
            validated.append({"max_budget": max_budget, "budget_duration": budget_duration})
        return validated

    def _request(self, method, path, body=None, *, key=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {key or self.master_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=10) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                pass
            raise LiteLLMError(error.code, detail) from error
        except (URLError, TimeoutError) as error:
            if isinstance(error, TimeoutError):
                raise RuntimeError(f"Timed out reaching LiteLLM at {self.base_url}") from error
            raise RuntimeError(f"Could not reach LiteLLM at {self.base_url}: {error.reason}") from error

    def key_for_user(self, user_id):
        user_name = f"user_{user_id}"
        digest = hmac.new(self.user_key_secret, user_name.encode(), hashlib.sha256).hexdigest()
        return f"sk-dojo-{digest}"

    def _key_exists(self, key):
        try:
            self._request("GET", f"/key/info?{urlencode({'key': key})}")
            return True
        except LiteLLMError as error:
            if error.status != 404:
                raise
            return False

    def ensure_key(self, user_id):
        user_name = f"user_{user_id}"
        key = self.key_for_user(user_id)
        if self._key_exists(key):
            return key
        self._request(
            "POST",
            "/key/generate",
            {
                "key": key,
                "user_id": user_name,
                "key_alias": user_name,
                "key_type": "llm_api",
                "models": ["all-proxy-models"],
                "budget_limits": self.budget_limits,
                "metadata": {"dojo_user_id": user_name},
            },
        )

        return key

    def credentials(self, user_id):
        key = self.ensure_key(user_id)
        models_response = self._request("GET", "/v1/models", key=key)
        models = [
            model["id"]
            for model in models_response.get("data", [])
            if isinstance(model, dict) and isinstance(model.get("id"), str)
        ]
        default_model = models[0] if models else None
        return {"key": key, "default_model": default_model, "models": models}

    def usage(self, user_id):
        user_name = f"user_{user_id}"
        query = urlencode({
            "start_date": "1970-01-01",
            "end_date": datetime.now(timezone.utc).date().isoformat(),
            "user_id": user_name,
        })
        response = self._request("GET", f"/user/daily/activity/aggregated?{query}")
        metadata = response.get("metadata") or {}
        models = {}
        metric_names = (
            "spend",
            "prompt_tokens",
            "completion_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "total_tokens",
            "api_requests",
        )
        for daily_usage in response.get("results") or []:
            breakdown = daily_usage.get("breakdown") or {}
            for model, model_usage in (breakdown.get("models") or {}).items():
                metrics = model_usage.get("metrics") or {}
                totals = models.setdefault(model, {name: 0 for name in metric_names})
                for name in metric_names:
                    totals[name] += metrics.get(name) or 0

        return {
            "spend": metadata.get("total_spend") or 0,
            "prompt_tokens": metadata.get("total_prompt_tokens") or 0,
            "completion_tokens": metadata.get("total_completion_tokens") or 0,
            "cache_read_input_tokens": metadata.get("total_cache_read_input_tokens") or 0,
            "cache_creation_input_tokens": metadata.get("total_cache_creation_input_tokens") or 0,
            "total_tokens": metadata.get("total_tokens") or 0,
            "api_requests": metadata.get("total_api_requests") or 0,
            "successful_requests": metadata.get("total_successful_requests") or 0,
            "failed_requests": metadata.get("total_failed_requests") or 0,
            "models": [
                {"model": model, **metrics}
                for model, metrics in sorted(
                    models.items(),
                    key=lambda item: item[1]["spend"],
                    reverse=True,
                )
            ],
        }
