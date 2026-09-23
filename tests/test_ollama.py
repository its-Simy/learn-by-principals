"""BL-036: the Ollama housekeeping provider, against a mocked Ollama HTTP server on loopback."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.ledger.ledger import Ledger
from core.memory.db import connect
from core.providers.lms.base import Resource
from core.providers.models.base import ModelError, ProviderState, TaskPackage
from core.providers.models.ollama import OllamaProvider
from core.router.router import NoProvider, Router
from core.sync.classify import ModelClassifier, classify
from tests.fakes.fake_models import FakeModel


class FakeOllama(BaseHTTPRequestHandler):
    models = ["llama3.2:3b"]
    reply = "lectures"
    status = 200
    requests: list = []

    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).requests.append(("GET", self.path, None))
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": n} for n in type(self).models]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        type(self).requests.append(("POST", self.path, body))
        if type(self).status != 200:
            self._send(type(self).status, {"error": f"model '{body['model']}' not found"})
            return
        self._send(
            200,
            {
                "model": body["model"],
                "response": type(self).reply,
                "done": True,
                "prompt_eval_count": 42,
                "eval_count": 2,
            },
        )


@pytest.fixture
def server():
    FakeOllama.models, FakeOllama.reply, FakeOllama.status = ["llama3.2:3b"], "lectures", 200
    FakeOllama.requests = []
    httpd = HTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def closed_port() -> str:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"  # nothing listens once closed


def classify_task(user="Title: dweight2"):
    return TaskPackage("classify", None, "Sort files.", user, 10)


def test_run_posts_to_generate_and_reports_usage(server):
    provider = OllamaProvider(server)
    result = provider.run(classify_task())

    assert (result.text, result.provider, result.model) == ("lectures", "ollama", "llama3.2:3b")
    assert (result.usage_hint.input_tokens, result.usage_hint.output_tokens) == (42, 2)
    (method, path, body) = FakeOllama.requests[-1]
    assert (method, path) == ("POST", "/api/generate")
    assert body["model"] == "llama3.2:3b" and body["stream"] is False
    assert body["system"] == "Sort files." and body["options"] == {"num_predict": 10}
    assert provider.state is ProviderState.AVAILABLE


def test_health_is_get_api_tags(server):
    provider = OllamaProvider(server)
    assert provider.health() is ProviderState.AVAILABLE
    assert FakeOllama.requests == [("GET", "/api/tags", None)]
    provider.health()
    assert len(FakeOllama.requests) == 1  # cached for a minute


def test_health_without_the_model_pulled_is_disabled(server):
    FakeOllama.models = ["mistral:7b"]
    provider = OllamaProvider(server)
    assert provider.health() is ProviderState.DISABLED
    assert "ollama pull llama3.2:3b" in provider.detail


def test_not_running_is_disabled():
    provider = OllamaProvider(closed_port(), timeout_s=2)
    assert provider.health() is ProviderState.DISABLED
    with pytest.raises(ModelError, match="not running"):
        provider.run(classify_task())


def test_http_error_is_broken(server):
    FakeOllama.status = 404
    provider = OllamaProvider(server)
    with pytest.raises(ModelError, match="HTTP 404"):
        provider.run(classify_task())
    assert provider.state is ProviderState.BROKEN


def test_model_comes_from_config(config):
    from dataclasses import replace

    provider = OllamaProvider.from_config(replace(config, ollama_model="qwen2.5:1.5b"))
    assert provider.model == "qwen2.5:1.5b" and provider.base_url == "http://localhost:11434"


def test_provider_refuses_other_task_types(server):
    with pytest.raises(ModelError, match="not explain"):
        OllamaProvider(server).run(TaskPackage("explain", None, "", "q"))
    assert FakeOllama.requests == []


def test_router_refuses_explain_on_ollama(server):
    router = Router({"ollama": OllamaProvider(server)}, Ledger(connect(":memory:")))
    with pytest.raises(NoProvider, match="ollama doesn't take explain"):
        router.route("explain")
    assert router.route("summarize").name == "ollama"


def test_ollama_is_first_for_classify_and_last_for_other_housekeeping(server):
    from core.config import DEFAULT_ROUTING

    models = {
        "ollama": OllamaProvider(server),
        "claude": FakeModel("claude"),
        "codex": FakeModel("codex"),
    }
    router = Router(models, Ledger(connect(":memory:")), DEFAULT_ROUTING)
    assert router.candidates("classify") == ["ollama", "claude", "codex"]
    assert router.candidates("extract_metadata") == ["claude", "codex", "ollama"]
    assert "ollama" not in router.candidates("explain")


# -- the classifier's fallback ----------------------------------------------------------------


def res(title, module="Week 1"):
    return Resource(1, 1, module, title, "File", None, None)


def classifier(provider):
    return ModelClassifier(Router({"ollama": provider}, Ledger(connect(":memory:"))))


def test_ambiguous_title_goes_to_ollama_when_available(server):
    FakeOllama.reply = "Labs."
    assert classify(res("dweight2"), "dweight2", classifier(OllamaProvider(server))) == "labs"
    (_, path, body) = FakeOllama.requests[-1]
    assert path == "/api/generate" and "dweight2" in body["prompt"]


def test_clear_titles_never_ask(server):
    assert classify(res("Lecture 3"), "lec3.pdf", classifier(OllamaProvider(server))) == "lectures"
    assert FakeOllama.requests == []


def test_unavailable_ollama_is_not_asked(server):
    FakeOllama.models = []  # running, model not pulled: DISABLED
    assert classify(res("dweight2"), "dweight2", classifier(OllamaProvider(server))) == "other"
    assert [r[1] for r in FakeOllama.requests] == ["/api/tags"]
    assert (
        classify(
            res("dweight2"), "dweight2", classifier(OllamaProvider(closed_port(), timeout_s=2))
        )
        == "other"
    )


def test_an_answer_that_is_not_a_bucket_is_ignored(server):
    FakeOllama.reply = "I think this is a spreadsheet"
    assert classify(res("dweight2"), "dweight2", classifier(OllamaProvider(server))) == "other"


def test_doctor_reports_ollama_as_optional(server):
    from cli import doctor

    assert doctor.check_ollama(OllamaProvider(server)).status is doctor.Status.OK
    missing = doctor.check_ollama(OllamaProvider(closed_port(), timeout_s=2))
    assert missing.status is doctor.Status.WARN and "not running" in missing.detail
