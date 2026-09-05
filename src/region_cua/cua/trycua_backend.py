"""trycua backend —— 阿里 cua-driver 适配层。

通过 ``cua-driver call <tool> --args '<json>'`` 子进程调用本地 UIA 驱动。

cua-driver 工具清单（已验证 0.18.0）：
- get_desktop_state : 全屏截图（base64 PNG）+ 可交互元素
- get_window_state  : 指定 pid 窗口截图 + UIA 控件树
- click / right_click / double_click : 坐标点击（带 pid，PostMessage 后台）
- type_text : WM_CHAR PostMessage 后台输入
- hotkey : 组合键
- scroll : 滚动
- drag : 拖拽
- list_windows / list_apps : 枚举窗口/进程

视觉定位策略（与 qwen-ui 的差异点）：
cua-driver 提供 UIA 控件树 + 元素文本，定位优先走「控件树文本匹配」
（比像素更稳，不依赖 VLM）；匹配不到再退回坐标映射 / 全屏 OCR。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import time
from typing import Optional

from ..cua import CuaBackend, Located

log = logging.getLogger(__name__)

_DEFAULT_BIN = "cua-driver"


class TryCuaBackend(CuaBackend):
    name = "trycua"

    def __init__(self, bin_path: Optional[str] = None, timeout: int = 30):
        self.bin = bin_path or os.environ.get("CUA_DRIVER_BIN") or _DEFAULT_BIN
        if shutil.which(self.bin) is None and not os.path.exists(self.bin):
            raise FileNotFoundError(
                f"cua-driver 未找到: {self.bin!r}。请确认已在 PATH 或设置 CUA_DRIVER_BIN。"
            )
        self.timeout = timeout
        self._last_windows: list[dict] = []
        self._target_pid: Optional[int] = None
        self._target_window_id: Optional[int] = None
        self._win_bounds: tuple[int, int] = (0, 0)  # 目标窗口左上角
        # UIA 未命中时的视觉回退引擎（Ollama VLM，懒加载）
        self._vlm = None
        self.vlm_use: bool = os.environ.get("TRYCUA_VLM_FALLBACK", "1") != "0"

    @property
    def vlm(self):
        """视觉回退引擎（Ollama VLM）。懒加载，避免无谓启动。"""
        if self._vlm is None and self.vlm_use:
            try:
                from .qwenui_backend import QwenUIAgentBackend
                self._vlm = QwenUIAgentBackend()
            except Exception:
                self._vlm = None
        return self._vlm

    # ------------------------------------------------------------ 子进程
    def ensure_target(self, window_keyword: Optional[str] = None) -> None:
        """确保已解析目标窗口 pid（供 click/type 定位）。executor 在操作前调用。"""
        if self._target_pid is None and window_keyword:
            self._resolve_target(window_keyword)
        if self._target_pid is None:
            raise RuntimeError("CUA backend 未解析目标窗口 pid，请先传 window_keyword")

    def _call(self, tool: str, args: Optional[dict] = None, timeout: Optional[int] = None) -> dict:
        cmd = [self.bin, "call", tool]
        if args:
            cmd += ["--args", json.dumps(args, ensure_ascii=False)]
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout or self.timeout, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {"error": f"cua-driver {tool} 超时", "refused": True}
        out = (p.stdout or "").strip()
        if not out:
            return {"error": (p.stderr or f"exit {p.returncode}").strip()[:300], "refused": True}
        try:
            res = json.loads(out)
        except json.JSONDecodeError:
            res = {"raw": out, "refused": p.returncode != 0}
        # 记录 driver 响应（除截图类大输出），便于诊断点击/输入为何不生效
        if tool in ("click", "right_click", "double_click", "type_text", "hotkey"):
            code = res.get("code") or res.get("effect") or ""
            if code and code not in ("success", "confirmed"):
                logging.getLogger(__name__).warning(
                    f"cua-driver {tool} 响应异常: code={code} effect={res.get('effect')} args={json.dumps(args, ensure_ascii=False)[:200]}"
                )
        return res

    # ------------------------------------------------------------ 截图
    def capture(self, shot_path: str, window_keyword: Optional[str] = None) -> str:
        """截图目标窗口（get_window_state 截指定窗口，不依赖前台）或全屏。

        - 有 window_keyword：get_window_state 截目标窗口（Chromium 也返回内容截图），
          坐标=窗口内坐标（与 executor._locate 一致）。
        - 无：get_desktop_state 全屏截图。
        """
        if window_keyword:
            self._resolve_target(window_keyword)
            if self._target_pid and self._target_window_id:
                res = self._call(
                    "get_window_state",
                    {"pid": self._target_pid, "window_id": self._target_window_id},
                    timeout=self.timeout + 10,
                )
                b64 = self._extract_png_b64(res)
                if b64:
                    os.makedirs(os.path.dirname(shot_path), exist_ok=True)
                    with open(shot_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                    return shot_path
                log.warning(f"capture: get_window_state 无截图响应 kw={window_keyword!r}")
            else:
                log.warning(f"capture: _resolve_target 未命中 kw={window_keyword!r} pid={self._target_pid} wid={self._target_window_id}")
        # 回退：全屏截图
        res = self._call("get_desktop_state")
        b64 = self._extract_png_b64(res)
        if not b64:
            raise RuntimeError(f"trycua 截图失败: {res.get('error', res)}")
        os.makedirs(os.path.dirname(shot_path), exist_ok=True)
        with open(shot_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return shot_path

    @staticmethod
    def _extract_png_b64(res: dict) -> Optional[str]:
        """从 get_desktop_state 响应里抽出 base64 PNG。

        实测字段名是 ``screenshot_png_b64``；兼容其它可能的命名。
        """
        # 1) 已知字段名（get_desktop_state 实测）
        for key in ("screenshot_png_b64", "png_b64", "screenshot_b64"):
            v = res.get(key)
            if isinstance(v, str) and len(v) > 200:
                return v.split("base64,", 1)[-1]
        # 2) 通用嵌套结构
        for key in ("image", "screenshot", "png", "b64"):
            v = res.get(key)
            if isinstance(v, str) and "base64," in v:
                return v.split("base64,", 1)[1]
            if isinstance(v, str) and len(v) > 200:
                return v
            if isinstance(v, dict):
                inner = v.get("image") or v.get("data") or v.get("b64")
                if isinstance(inner, str) and len(inner) > 200:
                    return inner.split("base64,", 1)[-1]
        # 3) 兜底：遍历所有 string 值找最长的 base64
        cands = [v for v in res.values() if isinstance(v, str) and len(v) > 200]
        if cands:
            return max(cands, key=len).split("base64,", 1)[-1]
        return None

    # ------------------------------------------------------------ 窗口解析
    def _resolve_target(self, keyword: str) -> None:
        """把窗口关键词解析成 (pid, 左上角偏移)，供后续点击定位。"""
        res = self._call("list_windows")
        wins = res.get("_legacy_windows") or res.get("windows") or []
        self._last_windows = wins
        kw = keyword.lower() if keyword else ""
        # 排除崩溃恢复框等干扰窗口
        def _bad(title: str) -> bool:
            tl = title.lower()
            return any(b in tl for b in ("还原页面", "restore", "崩溃", "crash", "unexpectedly closed"))
        # 1) 优先精确匹配 keyword
        for w in wins:
            title = str(w.get("title", ""))
            if w.get("minimized") or _bad(title):
                continue
            if kw and (kw in title.lower()):
                self._set_target(w)
                return
        # 2) 回退：匹配任意非最小化的 Edge/Chrome 浏览器窗口（排除崩溃框）
        for w in wins:
            title = str(w.get("title", ""))
            if w.get("minimized") or _bad(title):
                continue
            tl = title.lower()
            if "microsoft edge" in tl or " - chrome" in tl or "google chrome" in tl:
                self._set_target(w)
                return
        # 未匹配：保持 pid=None（点击走全局坐标）

    def _set_target(self, w: dict) -> None:
        self._target_pid = w.get("pid")
        self._target_window_id = w.get("window_id")
        self._win_bounds = (int(w.get("x", 0) or 0), int(w.get("y", 0) or 0))

    def activate_window(self, keyword: str) -> None:
        """激活目标窗口到 OS 前台。

        1) 优先 cua-driver bring_to_front（AttachThreadInput 技巧）。
        2) 失败/ambiguous（Edge 多窗口时常见）→ fallback ctypes SetForegroundWindow + Alt 技巧。
        """
        self._resolve_target(keyword)
        if not self._target_pid:
            log.warning(f"activate_window: 未找到目标窗口 keyword={keyword!r}")
            return
        log.info(f"activate_window: pid={self._target_pid} wid={self._target_window_id} keyword={keyword!r}")
        args: dict = {"pid": self._target_pid}
        if self._target_window_id is not None:
            args["window_id"] = self._target_window_id
        ok = False
        try:
            res = self._call("bring_to_front", args)
            ok = not (res.get("refused") or "ambiguous" in str(res) or "error" in str(res).lower())
            if not ok:
                log.warning(f"bring_to_front 未成功: {str(res)[:150]}")
        except Exception as exc:
            log.warning(f"bring_to_front 异常: {exc}")
            ok = False
        if not ok:
            # fallback：Alt 技巧 + SetForegroundWindow 直接激活目标 hwnd
            try:
                import ctypes
                import time as _t
                user32 = ctypes.windll.user32
                user32.keybd_event(0x12, 0, 0, 0)       # Alt down
                user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
                _t.sleep(0.1)
                hwnd = user32.FindWindowW(None, None)
                # 用 list_windows 的 hwnd（_target_window_id 即 hwnd）
                if self._target_window_id:
                    user32.SetForegroundWindow(int(self._target_window_id))
                _t.sleep(0.3)
            except Exception:
                pass

    # ------------------------------------------------------------ 视觉定位
    def locate(self, screenshot_path: str, target_desc: str) -> Located:
        """UIA 控件树文本匹配优先；未命中回退 Ollama VLM 视觉定位。

        坐标统一返回**窗口内坐标**（与喂入的截图坐标系一致），由 executor 负责
        换算成屏幕绝对坐标后点击。UIA 的 bounds 是屏幕绝对坐标，需减去窗口
        左上角偏移归一化成窗口内坐标。
        """
        off_x, off_y = self._win_bounds  # 目标窗口左上角（屏幕绝对）
        # 1) 若已解析出目标窗口 pid+window_id，取该窗口 UIA 控件树做文本匹配
        if self._target_pid and self._target_window_id:
            ws = self._call("get_window_state",
                             {"pid": self._target_pid, "window_id": self._target_window_id},
                             timeout=self.timeout + 10)
            hit = self._match_uia_element(ws, target_desc)
            if hit:
                # UIA 屏幕绝对坐标 → 窗口内坐标
                return Located(x=max(0, hit.x - off_x), y=max(0, hit.y - off_y),
                               found=True, analysis=hit.analysis)
        # 2) 退回全屏 desktop state 的元素匹配
        ds = self._call("get_desktop_state", timeout=self.timeout + 10)
        hit = self._match_uia_element(ds, target_desc)
        if hit:
            return Located(x=max(0, hit.x - off_x), y=max(0, hit.y - off_y),
                           found=True, analysis=hit.analysis)
        # 3) UIA 拿不到（典型：浏览器网页 DOM 不在 UIA 树里）→ 回退 Ollama VLM 视觉定位
        #    VLM 看的就是窗口截图，返回的已是窗口内坐标，无需换算
        if self.vlm is not None:
            log.info("[trycua] UIA 未命中，回退 Ollama VLM 视觉定位: %r", target_desc)
            vl = self.vlm.locate(screenshot_path, target_desc)
            if vl.found:
                vl.analysis = f"trycua: UIA未中→VLM {vl.analysis}"
            return vl
        return Located(x=0, y=0, found=False, analysis=f"trycua: UIA 未匹配到「{target_desc}」")

    def _match_uia_element(self, state: dict, target_desc: str) -> Optional[Located]:
        """在 UIA 控件树里找文本/名称最匹配 target_desc 的元素。

        打分：名称/文本包含 target_desc（或反之）给高分；同分取第一个。
        元素坐标取 UIA 报告的 bounds 中心（屏幕绝对坐标）。
        """
        if not state or state.get("refused"):
            return None
        elements = state.get("elements") or state.get("uia_elements") or state.get("controls") or []
        if isinstance(elements, dict):
            elements = elements.get("elements", [])
        q = target_desc.strip().lower()
        best, best_score = None, 0
        for el in elements:
            name = str(el.get("name") or el.get("title") or el.get("label") or "").strip()
            text = str(el.get("text") or "").strip()
            if not name and not text:
                continue
            hay = (name + " " + text).lower()
            score = 0
            if q in hay:
                score += 10
            if name and name.lower() == q:
                score += 5
            if text and text.lower() == q:
                score += 3
            # 词级重叠（target 可能是短语）
            twords = [w for w in q.replace("/", " ").split() if len(w) > 1]
            if twords:
                overlap = sum(1 for w in twords if w in hay)
                score += overlap
            if score <= 0:
                continue
            cx, cy = self._element_center(el)
            if cx is None:
                continue
            if score > best_score:
                best_score = score
                best = Located(x=int(cx), y=int(cy), found=True,
                               analysis=f"trycua UIA: {name or text!r} @({cx:.0f},{cy:.0f}) score={score}")
        return best

    @staticmethod
    def _element_center(el: dict) -> Optional[tuple[float, float]]:
        """从元素 bounds 算中心点。bounds 可能是 dict{x,y,width,height} 或 [x1,y1,x2,y2]。"""
        b = el.get("bounds") or el.get("rect") or el.get("bbox")
        if isinstance(b, dict):
            try:
                x, y, w, h = b["x"], b["y"], b["width"], b["height"]
                return (x + w / 2, y + h / 2)
            except (KeyError, TypeError):
                pass
        elif isinstance(b, (list, tuple)) and len(b) == 4:
            x1, y1, x2, y2 = b
            if x2 > x1 and y2 > y1:
                return ((x1 + x2) / 2, (y1 + y2) / 2)
        return None

    # ------------------------------------------------------------ 操作
    def set_date_input(self, year: int, month: int, day: int) -> None:
        """通过 UIA 原生 date input 的 年/月/日 Spinner 设值，触发 DOM change。

        原生 <input type=date> 的分段控件暴露为 UIA Spinner；对其 set_value
        会更新 DOM value 并触发 change 事件（从而设置 __selectedDate）。
        """
        if not (self._target_pid and self._target_window_id):
            raise RuntimeError("set_date_input: 未解析目标窗口 pid/window_id")
        ws = self._call("get_window_state",
                        {"pid": self._target_pid, "window_id": self._target_window_id},
                        timeout=self.timeout + 10)
        els = ws.get("elements") or []
        spinners = {}
        for e in els:
            if e.get("role") == "Spinner":
                lbl = str(e.get("label", ""))
                if "年" in lbl:
                    spinners.setdefault("y", e.get("element_token"))
                elif "月" in lbl:
                    spinners.setdefault("m", e.get("element_token"))
                elif "日" in lbl:
                    spinners.setdefault("d", e.get("element_token"))
        if not all(k in spinners and spinners[k] for k in ("y", "m", "d")):
            raise RuntimeError(f"set_date_input: 未找到完整年/月/日 Spinner (found={list(spinners)})")
        for k, val in (("y", str(year)), ("m", f"{month:02d}"), ("d", f"{day:02d}")):
            res = self._call("set_value", {
                "pid": self._target_pid, "window_id": self._target_window_id,
                "element_token": spinners[k], "value": val,
            })
            log.info("set_date_input %s=%s -> %s", k, val, res.get("route", res.get("effect")))

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        """点击。

        接收**窗口内坐标**（与 get_window_state 窗口截图一致）。
        - left/middle/double_click：加窗口偏移转屏幕坐标，scope=desktop 点击。
        - right_click：right_click 工具不支持 desktop scope，必须 pid+窗口内坐标。
        """
        tool = {"left": "click", "right": "right_click", "middle": "click"}.get(button, "click")
        if button == "middle":
            tool = "click"
        if clicks >= 2 and button == "left":
            tool = "double_click"

        if tool == "right_click":
            # right_click 需要 pid + 窗口内坐标（非 desktop scope）
            args: dict = {"pid": self._target_pid, "x": int(x), "y": int(y)}
            if self._target_window_id is not None:
                args["window_id"] = self._target_window_id
        else:
            sx = int(x) + self._win_bounds[0]
            sy = int(y) + self._win_bounds[1]
            args: dict = {"scope": "desktop", "x": sx, "y": sy}
            if button == "middle":
                args["button"] = "middle"
        # 先 background（UIA Invoke / PostMessage，不抢前台）
        res = self._call(tool, args)
        # Chromium/Electron 内容 background 会丢事件 → 驱动返回 background_unavailable
        # 按驱动指示：先 background，失败才 foreground（SendInput，短暂切换后恢复）
        need_fg = res.get("refused") or "background_unavailable" in str(res) or "noop" in str(res).lower()
        if need_fg:
            args["delivery_mode"] = "foreground"
            res2 = self._call(tool, args)
            if res2.get("refused"):
                raise RuntimeError(f"cua-driver {tool} 点击失败(foreground): {res2}")
        elif res.get("effect") == "suspected_noop":
            args["delivery_mode"] = "foreground"
            self._call(tool, args)

    def _type_native(self, text: str) -> None:
        args: dict = {"pid": self._target_pid, "text": text}
        if self._target_window_id is not None:
            args["window_id"] = self._target_window_id
        res = self._call("type_text", args)
        # Chromium/Electron 内容 WM_CHAR 会静默丢弃，驱动返回 background_unavailable
        # 按驱动指示：background 失败 → foreground 重试（SendInput，Chromium 会接收）
        if res.get("refused") or "background_unavailable" in str(res) or "noop" in str(res).lower():
            args["delivery_mode"] = "foreground"
            res2 = self._call("type_text", args)
            if res2.get("refused") or "background_unavailable" in str(res2):
                raise RuntimeError(f"type_text 失败(foreground): {res2}")
        elif res.get("effect") == "suspected_noop":
            args["delivery_mode"] = "foreground"
            self._call("type_text", args)

    def hotkey(self, *keys: str) -> None:
        flat: list[str] = []
        for k in keys:
            flat.extend(p.strip() for p in str(k).replace(" ", "").split("+") if p.strip())
        if flat:
            args: dict = {"keys": flat}
            if self._target_pid is not None:
                args["pid"] = self._target_pid
            if self._target_window_id is not None:
                args["window_id"] = self._target_window_id
            self._call("hotkey", args)

    def scroll(self, amount: int) -> None:
        self._call("scroll", {"pid": self._target_pid, "amount": amount})
