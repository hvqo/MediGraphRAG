import json
import httpx


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, store):
        self.store = store

    def _headers(self):
        return {'Authorization': 'Bearer ' + self.store.key()}

    async def check(self):
        settings = self.store.get()
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                if settings.provider == 'ollama':
                    response = await client.get(settings.ollama_base_url + '/api/tags')
                    response.raise_for_status()
                    names = [item['name'] for item in response.json().get('models', [])]
                    matched = settings.ollama_model in names or settings.ollama_model + ':latest' in names
                    return {'ok': matched, 'message': '模型可用' if matched else '服务已连接，但指定模型尚未下载', 'models': names}
                if not settings.cloud_base_url or not settings.cloud_model or not self.store.key():
                    return {'ok': False, 'message': '请填写云端地址、模型名称和 API 密钥'}
                response = await client.get(settings.cloud_base_url + '/models', headers=self._headers())
                response.raise_for_status()
                return {'ok': True, 'message': '服务已连接；模型可调用性以实际生成结果为准',
                        'models': [item['id'] for item in response.json().get('data', [])]}
        except (httpx.HTTPError, ValueError, KeyError):
            return {'ok': False, 'message': '无法连接模型服务，请检查地址、网络或凭据'}

    async def json(self, system, prompt):
        settings = self.store.get()
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout, trust_env=False) as client:
                if settings.provider == 'ollama':
                    response = await client.post(settings.ollama_base_url + '/api/chat', json={
                        'model': settings.ollama_model, 'messages': messages, 'stream': False, 'format': 'json',
                        'options': {'temperature': 0.15, 'num_ctx': 8192}})
                    response.raise_for_status()
                    content = response.json()['message']['content']
                else:
                    if not settings.cloud_base_url or not settings.cloud_model or not self.store.key():
                        raise ModelError('云端模型尚未配置完整')
                    response = await client.post(settings.cloud_base_url + '/chat/completions', headers=self._headers(), json={
                        'model': settings.cloud_model, 'messages': messages, 'temperature': 0.15,
                        'response_format': {'type': 'json_object'}})
                    response.raise_for_status()
                    content = response.json()['choices'][0]['message']['content']
            content = content.strip()
            if content.startswith('```'):
                content = content.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError('Expected JSON object')
            return result
        except ModelError:
            raise
        except httpx.HTTPStatusError as exc:
            raise ModelError(f'模型服务返回 HTTP {exc.response.status_code}，请检查模型和配置') from None
        except httpx.HTTPError:
            raise ModelError('模型服务连接失败或超时，请检查服务状态') from None
        except (ValueError, KeyError, TypeError):
            raise ModelError('模型没有返回有效的结构化结果，请重试或更换模型') from None
