import asyncio
import json
import logging
import os
import signal
import subprocess
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

logger = logging.getLogger("model-server")

MODEL_CONFIGS = {
    "qwen3.6-27b": {
        "model": "unsloth/Qwen3.6-27B-NVFP4",
        "tensor_parallel_size": 1,
        "cuda_devices": "0",
        "extra_args": [
            "--served-model-name", "qwen3.6-27b",
            "--trust-remote-code",
            "--language-model-only",
            "--max-model-len", "262144",
            "--max-num-seqs", "256",
            "--max-num-batched-tokens", "16384",
            "--enable-chunked-prefill",
            "--enable-prefix-caching",
            "--async-scheduling",
            "--gpu-memory-utilization", "0.95",
            "--kv-cache-dtype", "fp8",
            "--enable-auto-tool-choice",
            "--tool-call-parser", "qwen3_coder",
            "--reasoning-parser", "qwen3",
        ],
    },
    "qwen3.6-35b-a3b": {
        "model": "unsloth/Qwen3.6-35B-A3B-NVFP4",
        "tensor_parallel_size": 1,
        "cuda_devices": "1",
        "extra_args": [
            "--served-model-name", "qwen3.6-35b-a3b",
            "--trust-remote-code",
            "--language-model-only",
            "--max-model-len", "262144",
            "--max-num-seqs", "512",
            "--max-num-batched-tokens", "8192",
            "--enable-chunked-prefill",
            "--enable-prefix-caching",
            "--async-scheduling",
            "--gpu-memory-utilization", "0.95",
            "--kv-cache-dtype", "fp8",
            "--enable-auto-tool-choice",
            "--tool-call-parser", "qwen3_coder",
            "--reasoning-parser", "qwen3",
        ],
    },
    "deepseek-v4-flash": {
        "model": "deepseek-ai/DeepSeek-V4-Flash",
        "tensor_parallel_size": 2,
        "cuda_devices": "0,1",
        "extra_args": [
            "--served-model-name", "deepseek-v4-flash",
            "--trust-remote-code",
            "--kv-cache-dtype", "fp8",
            "--block-size", "256",
            "--load-format", "auto",
            "--gpu-memory-utilization", "0.90",
            "--max-model-len", "262144",
            "--max-num-seqs", "128",
            "--max-num-batched-tokens", "8192",
            "--max-cudagraph-capture-size", "256",
            "--compilation-config", '{"cudagraph_mode":"FULL_AND_PIECEWISE","custom_ops":["all"]}',
            "--async-scheduling",
            "--no-scheduler-reserve-full-isl",
            "--enable-chunked-prefill",
            "--enable-prefix-caching",
            "--enable-flashinfer-autotune",
            "--tokenizer-mode", "deepseek_v4",
            "--tool-call-parser", "deepseek_v4",
            "--reasoning-parser", "deepseek_v4",
            "--enable-auto-tool-choice",
            "--default-chat-template-kwargs.thinking=true",
            "--default-chat-template-kwargs.reasoning_effort=high",
            "--attention-backend", "B12X_MLA_SPARSE",
            "--moe-backend", "b12x",
            "--linear-backend", "b12x",
        ],
    },
}

VLLM_BIN = os.getenv("VLLM_BIN", "vllm")
HF_HOME = os.getenv("HF_HOME", "/models")
VLLM_PORT = 8000
LOAD_TIMEOUT = int(os.getenv("LOAD_TIMEOUT", "600"))


class ModelManager:
    def __init__(self):
        self._switch_lock = asyncio.Lock()
        self._switch_event = asyncio.Event()
        self._drained = asyncio.Condition()

        self.current_model: Optional[str] = None
        self.process: Optional[asyncio.subprocess.Process] = None
        self.process_start_time: float = 0.0
        self.ready: bool = False
        self._switching_to: Optional[str] = None
        self._inflight: int = 0

    # ── public API ──────────────────────────────────────────────

    async def ensure_model(self, model_id: str) -> bool:
        """Fast-path if already loaded; otherwise wait for (or initiate) a switch."""
        if self.current_model == model_id and self.ready:
            return True

        if self._switching_to == model_id:
            await self._switch_event.wait()
            return self.ready

        if self._switching_to is not None:
            await self._switch_event.wait()
            return await self.ensure_model(model_id)

        async with self._switch_lock:
            if self.current_model == model_id and self.ready:
                return True

            await self._wait_drained()

            self._switch_event.clear()
            self._switching_to = model_id
            try:
                await self._do_switch(model_id)
            finally:
                self._switching_to = None
                self._switch_event.set()
            return self.ready

    async def stop(self):
        await self._stop_current()

    # ── drain ───────────────────────────────────────────────────

    async def _wait_drained(self):
        async with self._drained:
            await self._drained.wait_for(lambda: self._inflight == 0)

    def _acquire_inflight(self):
        self._inflight += 1

    def _release_inflight(self):
        self._inflight -= 1
        if self._inflight == 0:
            self._drained.notify_all()

    # ── model lifecycle ─────────────────────────────────────────

    async def _do_switch(self, model_id: str):
        await self._stop_current()
        await self._start(model_id)

    async def _stop_current(self):
        if self.process is None:
            return
        logger.info("stopping vLLM (pid=%d)", self.process.pid)
        self.process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                timeout=30,
            )
        except asyncio.TimeoutError:
            logger.warning("SIGKILL after timeout")
            self.process.kill()
            await asyncio.get_event_loop().run_in_executor(None, self.process.wait)

        self.process = None
        self.ready = False
        self.current_model = None
        self.process_start_time = 0.0

    async def _start(self, model_id: str):
        cfg = MODEL_CONFIGS[model_id]
        cmd = [
            VLLM_BIN, "serve",
            cfg["model"],
            "--host", "127.0.0.1",
            "--port", str(VLLM_PORT),
            "--tensor-parallel-size", str(cfg["tensor_parallel_size"]),
        ] + cfg["extra_args"]

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = cfg["cuda_devices"]
        env["HF_HOME"] = HF_HOME
        if model_id == "deepseek-v4-flash":
            env.update(self._deepseek_env())

        logger.info("starting %s on GPU=%s TP=%d",
                     model_id, cfg["cuda_devices"], cfg["tensor_parallel_size"])

        self.process = await asyncio.create_subprocess_exec(
            *cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.current_model = model_id
        self.process_start_time = time.time()

        self.ready = await self._wait_ready(LOAD_TIMEOUT)
        if self.ready:
            logger.info("%s ready (%.1fs)", model_id, time.time() - self.process_start_time)
        else:
            logger.error("%s failed to start within %ds", model_id, LOAD_TIMEOUT)

    async def _wait_ready(self, timeout: int) -> bool:
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{VLLM_PORT}/v1/models"
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                try:
                    resp = await client.get(url, timeout=5)
                    if resp.status_code == 200:
                        return True
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass
                await asyncio.sleep(2)
        return False

    # ── proxy ───────────────────────────────────────────────────

    async def proxy(self, method: str, path: str, headers: dict, body: bytes) -> Response:
        target_url = f"http://127.0.0.1:{VLLM_PORT}/v1/{path}"
        clean_headers = {k: v for k, v in headers.items() if k.lower() != "host"}

        is_stream = False
        if path == "chat/completions" and body:
            try:
                is_stream = json.loads(body).get("stream", False)
            except Exception:
                pass

        if is_stream:
            return await self._proxy_stream(target_url, clean_headers, body)

        self._acquire_inflight()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
                resp = await client.request(
                    method=method, url=target_url, headers=clean_headers, content=body,
                )
                return Response(
                    content=resp.content, status_code=resp.status_code,
                    headers=dict(resp.headers),
                )
        finally:
            self._release_inflight()

    async def _proxy_stream(self, url: str, headers: dict, body: bytes) -> StreamingResponse:
        self._acquire_inflight()
        client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))

        async def generate() -> AsyncGenerator[bytes, None]:
            try:
                async with client.stream("POST", url, headers=headers, content=body) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            finally:
                self._release_inflight()
                await client.aclose()

        return StreamingResponse(generate(), media_type="text/event-stream")

    @staticmethod
    def _deepseek_env() -> dict:
        return {
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
            "CUTE_DSL_ARCH": "sm_120a",
            "NCCL_IB_DISABLE": "1",
            "NCCL_P2P_LEVEL": "SYS",
            "NCCL_PROTO": "LL,LL128,Simple",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            "VLLM_PREFIX_CACHE_RETENTION_INTERVAL": "4096",
            "VLLM_USE_AOT_COMPILE": "1",
            "VLLM_USE_MEGA_AOT_ARTIFACT": "1",
            "VLLM_USE_BREAKABLE_CUDAGRAPH": "0",
            "VLLM_USE_V2_MODEL_RUNNER": "1",
            "VLLM_USE_FLASHINFER_SAMPLER": "1",
            "VLLM_USE_B12X_WO_PROJECTION": "1",
            "VLLM_USE_B12X_MHC": "1",
            "VLLM_USE_B12X_FP8_GEMM": "1",
            "VLLM_USE_B12X_MOE": "1",
            "VLLM_USE_B12X_SPARSE_INDEXER": "1",
            "VLLM_ENABLE_PCIE_ALLREDUCE": "1",
            "VLLM_PCIE_ALLREDUCE_BACKEND": "b12x",
            "B12X_MLA_SM120_UNIFIED": "1",
            "B12X_MHC_MAX_TOKENS": "16384",
            "B12X_DENSE_SPLITK_TURBO": "1",
            "B12X_W4A16_TC_DECODE": "1",
        }


manager = ModelManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await manager.stop()


app = FastAPI(title="LLM Model Server", version="2.2.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok" if manager.ready else "loading",
        "current_model": manager.current_model,
        "switching": manager._switching_to is not None,
    }


@app.get("/status")
async def status():
    return {
        "current_model": manager.current_model,
        "ready": manager.ready,
        "switching": manager._switching_to is not None,
        "switching_to": manager._switching_to,
        "inflight": manager._inflight,
        "uptime": time.time() - manager.process_start_time if manager.process_start_time else 0,
        "available_models": list(MODEL_CONFIGS.keys()),
        "model_details": {
            mid: {"gpu": cfg["cuda_devices"], "tensor_parallel": cfg["tensor_parallel_size"]}
            for mid, cfg in MODEL_CONFIGS.items()
        },
    }


@app.post("/load")
async def load_model(body: dict):
    model_id = body.get("model")
    if not model_id:
        raise HTTPException(400, "Field 'model' is required")
    if model_id not in MODEL_CONFIGS:
        raise HTTPException(404, f"Unknown model '{model_id}'")

    if manager.current_model == model_id and manager.ready:
        return {"status": "already_loaded", "model": model_id}

    ok = await manager.ensure_model(model_id)
    if not ok:
        raise HTTPException(503, f"Failed to load model '{model_id}'")
    return {"status": "loaded", "model": model_id}


@app.post("/unload")
async def unload_model():
    await manager.stop()
    return {"status": "unloaded"}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": mid,
                "object": "model",
                "served": manager.current_model == mid and manager.ready,
                "owned_by": "model-server",
            }
            for mid in MODEL_CONFIGS
        ],
    }


@app.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy(request: Request, path: str):
    body_bytes = await request.body()

    model_id = None
    if request.method == "POST" and body_bytes:
        try:
            model_id = json.loads(body_bytes).get("model")
        except Exception:
            pass

    if model_id and model_id not in MODEL_CONFIGS:
        raise HTTPException(404, f"Unknown model '{model_id}'")

    if not model_id:
        if manager.current_model and manager.ready:
            model_id = manager.current_model
        else:
            raise HTTPException(
                400,
                "No model specified and no model is loaded. "
                "Set 'model' in the request body.",
            )

    ok = await manager.ensure_model(model_id)
    if not ok:
        raise HTTPException(503, f"Failed to load model '{model_id}'")

    return await manager.proxy(request.method, path, dict(request.headers), body_bytes)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    uvicorn.run("main:app", host="0.0.0.0", port=8001, log_level="info")
