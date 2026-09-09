import argparse
import base64
import contextlib
import hashlib
import json
import math
import os
import pathlib
import platform
import re
import shlex
import shutil
import socket
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

import requests
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait

from utils import DOJO_URL, workspace_run


@dataclass(frozen=True)
class LinkProfile:
    name: str
    one_way_delay_ms: int
    rate: str | None
    loss_percent_per_direction: float

    @property
    def estimated_rtt_ms(self):
        return self.one_way_delay_ms * 2


PROFILES = {
    profile.name: profile
    for profile in (
        LinkProfile("clean", 0, None, 0),
        LinkProfile("wan", 25, "20mbit", 0),
        LinkProfile("mobile", 75, "4mbit", 0.5),
        LinkProfile("poor", 150, "1mbit", 1),
    )
}


class ShapingUnavailable(RuntimeError):
    pass


class LocalLinkShaper:
    def __init__(self, interface, ifb_interface="ifbbench0"):
        self.interface = interface
        self.ifb_interface = ifb_interface
        self.tc = shutil.which("tc")
        self.ip = shutil.which("ip")
        self.created_ifb = False
        self.installed_ingress = False
        self.installed_root = False

    def _run(self, *command, check=True):
        return subprocess.run(command, check=check, capture_output=True, text=True)

    def _tc_json(self, *command):
        result = self._run(self.tc, "-j", *command, check=False)
        if result.returncode:
            raise ShapingUnavailable(
                f"tc {' '.join(command)} failed: {result.stderr.strip()}"
            )
        try:
            state = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as error:
            raise ShapingUnavailable(
                f"tc {' '.join(command)} returned invalid JSON: {error}"
            ) from error
        if not isinstance(state, list):
            raise ShapingUnavailable(
                f"tc {' '.join(command)} returned unexpected state: {state!r}"
            )
        return state

    def _ensure_pristine(self):
        if not self.tc or not self.ip:
            raise ShapingUnavailable(
                "local shaping requires iproute2 (ip and tc); install it in the disposable client "
                "or shape its host peer and use --shaping external"
            )
        if not pathlib.Path(f"/sys/class/net/{self.interface}").exists():
            raise ShapingUnavailable(f"network interface {self.interface!r} does not exist")
        if pathlib.Path(f"/sys/class/net/{self.ifb_interface}").exists():
            raise ShapingUnavailable(
                f"refusing to reuse the existing benchmark IFB interface {self.ifb_interface}"
            )
        qdiscs = self._tc_json("qdisc", "show", "dev", self.interface)
        occupied = [
            qdisc
            for qdisc in qdiscs
            if qdisc.get("kind") != "noqueue" or not qdisc.get("root")
        ]
        if occupied:
            raise ShapingUnavailable(
                f"refusing to replace existing qdiscs on {self.interface}: {occupied!r}"
            )
        filters = {
            parent: self._tc_json(
                "filter", "show", "dev", self.interface, parent
            )
            for parent in ["root", "ingress", "egress"]
        }
        occupied_filters = {
            parent: state for parent, state in filters.items() if state
        }
        if occupied_filters:
            raise ShapingUnavailable(
                f"refusing to replace existing filters on {self.interface}: {occupied_filters!r}"
            )

    def apply(self, profile):
        self.cleanup()
        self._ensure_pristine()
        if profile.name == "clean":
            return
        created_ifb = self._run(
            self.ip, "link", "add", self.ifb_interface, "type", "ifb", check=False
        )
        if created_ifb.returncode:
            raise ShapingUnavailable(
                "the kernel could not create an IFB device for ingress shaping: "
                f"{created_ifb.stderr.strip()}; load the ifb module outside the client or shape its host peer "
                "and use --shaping external"
            )
        self.created_ifb = True
        try:
            self._run(self.ip, "link", "set", "dev", self.ifb_interface, "up")
            self._run(self.tc, "qdisc", "add", "dev", self.interface, "handle", "ffff:", "ingress")
            self.installed_ingress = True
            self._run(
                self.tc,
                "filter",
                "add",
                "dev",
                self.interface,
                "parent",
                "ffff:",
                "protocol",
                "all",
                "u32",
                "match",
                "u32",
                "0",
                "0",
                "action",
                "mirred",
                "egress",
                "redirect",
                "dev",
                self.ifb_interface,
            )
            netem = ["netem", "delay", f"{profile.one_way_delay_ms}ms"]
            if profile.loss_percent_per_direction:
                netem.extend(("loss", f"{profile.loss_percent_per_direction}%"))
            if profile.rate:
                netem.extend(("rate", profile.rate))
            self._run(self.tc, "qdisc", "add", "dev", self.interface, "root", *netem)
            self.installed_root = True
            self._run(self.tc, "qdisc", "add", "dev", self.ifb_interface, "root", *netem)
        except Exception:
            self.cleanup()
            raise

    def cleanup(self):
        if self.tc and self.installed_root:
            self._run(
                self.tc, "qdisc", "del", "dev", self.interface, "root", check=False
            )
        if self.tc and self.installed_ingress:
            self._run(
                self.tc,
                "qdisc",
                "del",
                "dev",
                self.interface,
                "ingress",
                check=False,
            )
        if self.ip and self.created_ifb:
            self._run(
                self.ip, "link", "del", "dev", self.ifb_interface, check=False
            )
        self.created_ifb = False
        self.installed_ingress = False
        self.installed_root = False

    def describe(self):
        if not self.tc:
            return None
        state = {
            self.interface: self._run(
                self.tc, "-s", "qdisc", "show", "dev", self.interface, check=False
            ).stdout.strip()
        }
        if pathlib.Path(f"/sys/class/net/{self.ifb_interface}").exists():
            state[self.ifb_interface] = self._run(
                self.tc, "-s", "qdisc", "show", "dev", self.ifb_interface, check=False
            ).stdout.strip()
        state["filters"] = {
            parent: self._run(
                self.tc,
                "-j",
                "filter",
                "show",
                "dev",
                self.interface,
                parent,
                check=False,
            ).stdout.strip()
            for parent in ["root", "ingress", "egress"]
        }
        return state

    def backlog_state(self):
        if not self.installed_root:
            return {
                "required": False,
                "available": True,
                "empty": True,
                "backlog_bytes": 0,
                "queued_packets": 0,
                "interfaces": {},
            }
        interfaces = {}
        for interface in [self.interface, self.ifb_interface]:
            qdiscs = self._tc_json(
                "-s", "qdisc", "show", "dev", interface, "root"
            )
            netem_qdiscs = [
                qdisc for qdisc in qdiscs if qdisc.get("kind") == "netem"
            ]
            if not netem_qdiscs:
                raise ShapingUnavailable(
                    f"expected a netem root qdisc on {interface}, got {qdiscs!r}"
                )
            backlog_bytes = max(
                int(qdisc.get("backlog", -1)) for qdisc in netem_qdiscs
            )
            queued_packets = max(
                int(qdisc.get("qlen", -1)) for qdisc in netem_qdiscs
            )
            interfaces[interface] = {
                "empty": backlog_bytes == 0 and queued_packets == 0,
                "backlog_bytes": backlog_bytes,
                "queued_packets": queued_packets,
                "qdiscs": netem_qdiscs,
            }
        return {
            "required": True,
            "available": True,
            "empty": all(state["empty"] for state in interfaces.values()),
            "backlog_bytes": sum(
                state["backlog_bytes"] for state in interfaces.values()
            ),
            "queued_packets": sum(
                state["queued_packets"] for state in interfaces.values()
            ),
            "interfaces": interfaces,
        }


def parse_csrf_token(text):
    match = re.search(r"'csrfNonce': \"(\w+)\"", text)
    if not match:
        raise RuntimeError("the login page did not contain a CSRF token")
    return match.group(1)


def login_session(base_url, user, password):
    session = requests.Session()
    response = session.get(f"{base_url}/login", timeout=30)
    response.raise_for_status()
    response = session.post(
        f"{base_url}/login",
        data={"name": user, "password": password, "nonce": parse_csrf_token(response.text)},
        allow_redirects=False,
        timeout=30,
    )
    if response.status_code != 302:
        raise RuntimeError(f"login failed with HTTP {response.status_code}")
    session.headers["CSRF-Token"] = parse_csrf_token(
        session.get(f"{base_url}/", timeout=30).text
    )
    return session


def warm_desktop(base_url, user, password):
    session = login_session(base_url, user, password)
    response = session.get(
        f"{base_url}/pwncollege_api/v1/workspace",
        params={"service": "desktop"},
        timeout=180,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("success") or not result.get("active"):
        raise RuntimeError(f"desktop workspace is not active: {result}")
    iframe_src = result.get("iframe_src")
    if iframe_src:
        response = session.get(iframe_src, timeout=180)
        response.raise_for_status()
    return iframe_src


def make_browser(width, height, page_load_timeout):
    options = FirefoxOptions()
    options.add_argument("--headless")
    options.add_argument(f"--width={width}")
    options.add_argument(f"--height={height}")
    options.set_preference("datareporting.healthreport.uploadEnabled", False)
    options.set_preference("datareporting.policy.dataSubmissionEnabled", False)
    options.set_preference("toolkit.telemetry.enabled", False)
    options.set_preference("app.normandy.enabled", False)
    options.set_preference("app.update.auto", False)
    options.set_preference("browser.safebrowsing.downloads.enabled", False)
    options.set_preference("browser.safebrowsing.malware.enabled", False)
    options.set_preference("browser.safebrowsing.phishing.enabled", False)
    options.set_preference("browser.search.update", False)
    options.set_preference("browser.startup.homepage", "about:blank")
    options.set_preference("network.captive-portal-service.enabled", False)
    options.set_preference("network.connectivity-service.enabled", False)
    geckodriver = shutil.which("geckodriver")
    service = FirefoxService(executable_path=geckodriver) if geckodriver else None
    browser = Firefox(options=options, service=service)
    browser.set_window_size(width, height)
    browser.set_page_load_timeout(page_load_timeout)
    return browser


def browser_login(browser, base_url, user, password):
    browser.get(f"{base_url}/login")
    browser.find_element(By.ID, "name").send_keys(user)
    browser.find_element(By.ID, "password").send_keys(password)
    browser.find_element(By.ID, "_submit").click()
    WebDriverWait(browser, 30).until(lambda driver: "/login" not in driver.current_url)


def visible_desktop_canvas(driver):
    canvases = [
        canvas
        for canvas in driver.find_elements(By.CSS_SELECTOR, "canvas")
        if canvas.is_displayed() and canvas.size["width"] >= 320 and canvas.size["height"] >= 200
    ]
    return max(canvases, key=lambda canvas: canvas.size["width"] * canvas.size["height"], default=False)


def canvas_dimensions(browser, canvas):
    return browser.execute_script(
        "return {css_width: arguments[0].getBoundingClientRect().width, "
        "css_height: arguments[0].getBoundingClientRect().height, "
        "buffer_width: arguments[0].width, buffer_height: arguments[0].height, "
        "device_pixel_ratio: window.devicePixelRatio};",
        canvas,
    )


def canvas_visual_digest(browser):
    canvas = visible_desktop_canvas(browser)
    if not canvas:
        raise RuntimeError("the desktop canvas is not visible")
    try:
        sample = browser.execute_script(
            "const source = arguments[0];"
            "const sample = document.createElement('canvas');"
            "sample.width = 32;"
            "sample.height = 18;"
            "const context = sample.getContext('2d', {willReadFrequently: true});"
            "context.imageSmoothingEnabled = true;"
            "context.imageSmoothingQuality = 'high';"
            "context.drawImage(source, 0, 0, sample.width, sample.height);"
            "const pixels = context.getImageData(0, 0, sample.width, sample.height).data;"
            "let quantized = '';"
            "for (let index = 0; index < pixels.length; index += 4) {"
            "quantized += (pixels[index] >> 4).toString(16);"
            "quantized += (pixels[index + 1] >> 4).toString(16);"
            "quantized += (pixels[index + 2] >> 4).toString(16);"
            "}"
            "return quantized;",
            canvas,
        )
        return {
            "digest": hashlib.sha256(sample.encode()).hexdigest(),
            "method": "32x18-rgb4-canvas-sha256",
        }
    except Exception:
        return {
            "digest": hashlib.sha256(canvas.screenshot_as_png).hexdigest(),
            "method": "canvas-element-png-sha256",
        }


def canvas_region_rgb(browser, canvas):
    return browser.execute_script(
        "const source = arguments[0];"
        "const size = 16;"
        "const sourceSize = Math.max(16, Math.floor(Math.min(source.width, source.height) / 12));"
        "const sourceX = Math.floor((source.width - sourceSize) / 2);"
        "const sourceY = Math.floor((source.height - sourceSize) / 2);"
        "const sample = document.createElement('canvas');"
        "sample.width = size;"
        "sample.height = size;"
        "const context = sample.getContext('2d', {willReadFrequently: true});"
        "context.drawImage(source, sourceX, sourceY, sourceSize, sourceSize, 0, 0, size, size);"
        "const pixels = context.getImageData(0, 0, size, size).data;"
        "const totals = [0, 0, 0];"
        "for (let index = 0; index < pixels.length; index += 4) {"
        "totals[0] += pixels[index];"
        "totals[1] += pixels[index + 1];"
        "totals[2] += pixels[index + 2];"
        "}"
        "const count = pixels.length / 4;"
        "return totals.map(total => Math.round(total / count));",
        canvas,
    )


def rgb_distance(first, second):
    return max(abs(left - right) for left, right in zip(first, second))


def wait_for_canvas_region_transition(
    browser,
    canvas,
    different_from,
    timeout,
    minimum_distance=48,
    stable_distance=4,
    stable_samples=3,
):
    deadline = time.monotonic() + timeout
    candidate = None
    matching_samples = 0
    while time.monotonic() < deadline:
        current = canvas_region_rgb(browser, canvas)
        if rgb_distance(current, different_from) >= minimum_distance:
            if candidate and rgb_distance(current, candidate) <= stable_distance:
                matching_samples += 1
            else:
                candidate = current
                matching_samples = 1
            if matching_samples >= stable_samples:
                return current
        else:
            candidate = None
            matching_samples = 0
        time.sleep(0.05)
    raise TimeoutException("the latency probe color transition was not visible")


def capture_latency_template(browser, canvas, name):
    return browser.execute_script(
        "const source = arguments[0];"
        "const name = arguments[1];"
        "const width = 192;"
        "const height = 108;"
        "const sample = document.createElement('canvas');"
        "sample.width = width;"
        "sample.height = height;"
        "const context = sample.getContext('2d', {willReadFrequently: true});"
        "context.imageSmoothingEnabled = false;"
        "context.drawImage(source, 0, 0, width, height);"
        "const pixels = Array.from(context.getImageData(0, 0, width, height).data);"
        "const calibration = window.__dojoLatencyCalibration || "
        "{width: width, height: height, templates: {}};"
        "calibration.templates[name] = pixels;"
        "calibration.mask = [];"
        "if (calibration.templates.a && calibration.templates.b) {"
        "const a = calibration.templates.a;"
        "const b = calibration.templates.b;"
        "for (let pixel = 0; pixel < width * height; pixel += 1) {"
        "const offset = pixel * 4;"
        "const difference = Math.abs(a[offset] - b[offset]) + "
        "Math.abs(a[offset + 1] - b[offset + 1]) + "
        "Math.abs(a[offset + 2] - b[offset + 2]);"
        "if (difference >= 48) calibration.mask.push(pixel);"
        "}"
        "}"
        "window.__dojoLatencyCalibration = calibration;"
        "return {name: name, width: width, height: height, "
        "discriminating_pixels: calibration.mask.length};",
        canvas,
        name,
    )


def latency_template_progress(browser, canvas, source_name, target_name):
    return browser.execute_script(
        "const source = arguments[0];"
        "const calibration = window.__dojoLatencyCalibration;"
        "const from = calibration.templates[arguments[1]];"
        "const to = calibration.templates[arguments[2]];"
        "const sample = document.createElement('canvas');"
        "sample.width = calibration.width;"
        "sample.height = calibration.height;"
        "const context = sample.getContext('2d', {willReadFrequently: true});"
        "context.imageSmoothingEnabled = false;"
        "context.drawImage(source, 0, 0, sample.width, sample.height);"
        "const current = context.getImageData(0, 0, sample.width, sample.height).data;"
        "let numerator = 0;"
        "let denominator = 0;"
        "for (const pixel of calibration.mask) {"
        "const offset = pixel * 4;"
        "for (let channel = 0; channel < 3; channel += 1) {"
        "const direction = to[offset + channel] - from[offset + channel];"
        "numerator += (current[offset + channel] - from[offset + channel]) * direction;"
        "denominator += direction * direction;"
        "}"
        "}"
        "return denominator ? numerator / denominator : null;",
        canvas,
        source_name,
        target_name,
    )


def wait_for_latency_template(
    browser,
    canvas,
    source_name,
    target_name,
    timeout,
    minimum_progress=0.98,
):
    deadline = time.monotonic() + timeout
    stable_samples = 0
    while time.monotonic() < deadline:
        progress = latency_template_progress(
            browser, canvas, source_name, target_name
        )
        if isinstance(progress, (int, float)) and progress >= minimum_progress:
            stable_samples += 1
            if stable_samples >= 2:
                return progress
        else:
            stable_samples = 0
        time.sleep(0.05)
    raise TimeoutException(f"latency template {target_name} was not stable")


def arm_canvas_latency_probe(browser, canvas, key, source_name, target_name, timeout):
    return browser.execute_script(
        "if (window.__dojoLatencyStop) window.__dojoLatencyStop();"
        "const source = arguments[0];"
        "const expectedKey = arguments[1];"
        "const sourceName = arguments[2];"
        "const targetName = arguments[3];"
        "const timeoutMs = arguments[4] * 1000;"
        "const calibration = window.__dojoLatencyCalibration;"
        "const from = calibration.templates[sourceName];"
        "const to = calibration.templates[targetName];"
        "const sample = document.createElement('canvas');"
        "sample.width = calibration.width;"
        "sample.height = calibration.height;"
        "const context = sample.getContext('2d', {willReadFrequently: true});"
        "context.imageSmoothingEnabled = false;"
        "const progress = () => {"
        "context.drawImage(source, 0, 0, sample.width, sample.height);"
        "const current = context.getImageData(0, 0, sample.width, sample.height).data;"
        "let numerator = 0;"
        "let denominator = 0;"
        "for (const pixel of calibration.mask) {"
        "const offset = pixel * 4;"
        "for (let channel = 0; channel < 3; channel += 1) {"
        "const direction = to[offset + channel] - from[offset + channel];"
        "numerator += (current[offset + channel] - from[offset + channel]) * direction;"
        "denominator += direction * direction;"
        "}"
        "}"
        "return denominator ? numerator / denominator : null;"
        "};"
        "const probe = {"
        "status: 'armed', key: expectedKey, source: sourceName, target: targetName,"
        "armed_at_ms: performance.now(), keydown_at_ms: null, keydown_trusted: null,"
        "event_timestamp_source: null, onset: null, settled: null, progress: null,"
        "frame_count: 0, raf_intervals_ms: [], last_frame_at_ms: null,"
        "initial_progress: progress()"
        "};"
        "let frameRequest;"
        "let onsetPending = null;"
        "let settledPending = null;"
        "let onsetLastNegative = null;"
        "let settledLastNegative = null;"
        "const stop = () => {"
        "window.removeEventListener('keydown', onKeydown, true);"
        "if (frameRequest) cancelAnimationFrame(frameRequest);"
        "window.__dojoLatencyStop = null;"
        "};"
        "const onKeydown = event => {"
        "if (probe.keydown_at_ms !== null || event.key !== expectedKey || event.repeat) return;"
        "const now = performance.now();"
        "const compatible = Math.abs(event.timeStamp - now) < 1000;"
        "probe.keydown_at_ms = compatible ? event.timeStamp : now;"
        "probe.event_timestamp_source = compatible ? 'KeyboardEvent.timeStamp' : 'performance.now';"
        "probe.keydown_trusted = event.isTrusted;"
        "probe.status = 'waiting_for_pixels';"
        "onsetLastNegative = probe.keydown_at_ms;"
        "settledLastNegative = probe.keydown_at_ms;"
        "};"
        "const observeThreshold = (value, threshold, pending, lastNegative, timestamp) => {"
        "if (value < threshold) return {pending: null, lastNegative: timestamp, result: null};"
        "if (pending === null) return {pending: timestamp, lastNegative: lastNegative, result: null};"
        "return {pending: pending, lastNegative: lastNegative, result: {"
        "lower_ms: Math.max(0, lastNegative - probe.keydown_at_ms),"
        "upper_ms: Math.max(0, pending - probe.keydown_at_ms),"
        "observation_interval_ms: Math.max(0, pending - lastNegative)"
        "}};"
        "};"
        "const sampleFrame = timestamp => {"
        "probe.frame_count += 1;"
        "if (probe.last_frame_at_ms !== null && probe.keydown_at_ms !== null) "
        "probe.raf_intervals_ms.push(timestamp - probe.last_frame_at_ms);"
        "probe.last_frame_at_ms = timestamp;"
        "try {"
        "probe.progress = progress();"
        "const observedAt = performance.now();"
        "if (probe.keydown_at_ms !== null) {"
        "const onsetState = observeThreshold(probe.progress, 0.10, onsetPending, onsetLastNegative, observedAt);"
        "onsetPending = onsetState.pending;"
        "onsetLastNegative = onsetState.lastNegative;"
        "if (!probe.onset && onsetState.result) probe.onset = onsetState.result;"
        "const settledState = observeThreshold(probe.progress, 0.90, settledPending, settledLastNegative, observedAt);"
        "settledPending = settledState.pending;"
        "settledLastNegative = settledState.lastNegative;"
        "if (!probe.settled && settledState.result) probe.settled = settledState.result;"
        "if (probe.onset && probe.settled) {"
        "probe.status = probe.keydown_trusted ? 'passed' : 'untrusted_input';"
        "stop();"
        "return;"
        "}"
        "}"
        "if (timestamp - probe.armed_at_ms >= timeoutMs) {"
        "probe.status = 'timed_out';"
        "stop();"
        "return;"
        "}"
        "frameRequest = requestAnimationFrame(sampleFrame);"
        "} catch (error) {"
        "probe.status = 'failed';"
        "probe.error = `${error.name}: ${error.message}`;"
        "stop();"
        "}"
        "};"
        "window.__dojoLatencyProbe = probe;"
        "window.__dojoLatencyStop = stop;"
        "window.addEventListener('keydown', onKeydown, true);"
        "frameRequest = requestAnimationFrame(sampleFrame);"
        "return {status: probe.status, initial_progress: probe.initial_progress};",
        canvas,
        key,
        source_name,
        target_name,
        timeout,
    )


def canvas_latency_probe_state(browser):
    return browser.execute_script(
        "const probe = window.__dojoLatencyProbe;"
        "if (!probe) return null;"
        "return {status: probe.status, key: probe.key, source: probe.source, target: probe.target, "
        "keydown_trusted: probe.keydown_trusted, event_timestamp_source: probe.event_timestamp_source, "
        "onset: probe.onset, settled: probe.settled, progress: probe.progress, "
        "initial_progress: probe.initial_progress, frame_count: probe.frame_count, "
        "raf_intervals_ms: probe.raf_intervals_ms, error: probe.error || null};"
    )


def sample_browser_delivery(browser, samples, started_at, phase):
    sample = {
        "seconds": round(time.monotonic() - started_at, 3),
        "phase": phase,
    }
    try:
        sample.update(canvas_visual_digest(browser))
    except Exception as error:
        sample["error"] = f"{type(error).__name__}: {error}"
    samples.append(sample)


def sample_browser_delivery_until(browser, samples, started_at, phase, deadline):
    while time.monotonic() < deadline:
        sample_browser_delivery(browser, samples, started_at, phase)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.5, remaining))
    sample_browser_delivery(browser, samples, started_at, phase)


def summarize_browser_delivery(samples):
    valid_samples = [sample for sample in samples if sample.get("digest")]
    error_samples = [sample for sample in samples if sample.get("error")]
    baseline = next(
        (sample for sample in valid_samples if sample["phase"] == "baseline"),
        None,
    )
    baseline_index = valid_samples.index(baseline) if baseline else -1
    comparable_samples = [
        sample
        for sample in valid_samples[baseline_index + 1:]
        if baseline and sample.get("method") == baseline.get("method")
    ]
    post_input_samples = [
        sample
        for sample in comparable_samples
        if sample["phase"] in ("workload", "traffic_drain")
    ]
    changed_samples = [
        sample
        for sample in post_input_samples
        if baseline and sample["digest"] != baseline["digest"]
    ]
    post_input_digests = {sample["digest"] for sample in post_input_samples}
    minimum_post_input_frames = (
        3 if baseline and baseline.get("method") == "canvas-element-png-sha256" else 2
    )
    digest_changes = sum(
        previous["digest"] != current["digest"]
        for previous, current in zip(
            [baseline, *post_input_samples], post_input_samples
        )
        if previous
    )
    return {
        "status": (
            "passed"
            if baseline
            and changed_samples
            and len(post_input_digests) >= minimum_post_input_frames
            and not error_samples
            else "failed"
        ),
        "sample_method": baseline.get("method") if baseline else None,
        "samples": samples,
        "sample_count": len(samples),
        "valid_sample_count": len(valid_samples),
        "error_count": len(error_samples),
        "unique_digest_count": len(
            {sample["digest"] for sample in valid_samples}
        ),
        "distinct_post_input_frames": len(post_input_digests),
        "minimum_post_input_frames": minimum_post_input_frames,
        "digest_change_count": digest_changes,
        "baseline_digest": baseline["digest"] if baseline else None,
        "final_digest": valid_samples[-1]["digest"] if valid_samples else None,
        "first_change_seconds": changed_samples[0]["seconds"] if changed_samples else None,
    }


def xpra_display_dimensions(browser, client):
    if client != "xpra":
        return None
    return browser.execute_script(
        "return {desktop_width: client.desktop_width, desktop_height: client.desktop_height, "
        "windows: Object.values(client.id_to_window).map(window => "
        "({width: window.w, height: window.h}))};"
    )


def desktop_is_frameless(browser, client):
    if client != "xpra":
        return True
    return browser.execute_script(
        "return Object.values(client.id_to_window).length > 0 && "
        "Object.values(client.id_to_window).every(window => !window.decorated);"
    )


def xpra_randr_dimensions(user, client):
    if client != "xpra":
        return None
    python_code = (
        "import json; "
        "from xpra.x11.bindings.display_source import init_display_source; "
        "init_display_source(); "
        "from xpra.x11.bindings.randr import RandRBindings; "
        "randr=RandRBindings(); "
        "properties=randr.get_all_screen_properties(); "
        "crtc=next(value for value in properties['crtcs'].values() if value.get('noutput')); "
        "print(json.dumps({'screen': randr.get_screen_size(), "
        "'crtc': [crtc['width'], crtc['height']]}))"
    )
    command = (
        "xpra_pid=$(cat /run/dojo/var/desktop-service/xpra.pid); "
        "xpra_python=$(readlink -f /proc/$xpra_pid/exe); "
        "xpra_entry=$(tr '\\0' '\\n' < /proc/$xpra_pid/cmdline | sed -n '2p'); "
        "xpra_root=$(dirname \"$(dirname \"$xpra_entry\")\"); "
        "xpra_site=$(find \"$xpra_root/lib\" -path '*/site-packages' -type d | head -1); "
        f"DISPLAY=:0 PYTHONPATH=\"$xpra_site\" \"$xpra_python\" -c {shlex.quote(python_code)}"
    )
    return json.loads(workspace_run(command, user=user).stdout)


def display_resize_state(browser, client, user):
    canvas = visible_desktop_canvas(browser)
    return (
        canvas,
        canvas_dimensions(browser, canvas) if canvas else None,
        xpra_display_dimensions(browser, client),
        xpra_randr_dimensions(user, client),
    )


def display_state_matches(client, surface, remote, randr):
    if not surface or surface["buffer_width"] <= 0 or surface["buffer_height"] <= 0:
        return False
    if client != "xpra":
        return True
    dimensions = [surface["buffer_width"], surface["buffer_height"]]
    return bool(
        remote
        and randr
        and [remote["desktop_width"], remote["desktop_height"]] == dimensions
        and any(
            [window["width"], window["height"]] == dimensions
            for window in remote["windows"]
        )
        and randr["screen"] == dimensions
        and randr["crtc"] == dimensions
    )


def wait_for_display_state(browser, client, user, timeout, expected=None, different_from=None):
    deadline = time.monotonic() + timeout
    state = (False, None, None, None)
    while time.monotonic() < deadline:
        state = display_resize_state(browser, client, user)
        _, surface, remote, randr = state
        dimensions = (
            [surface["buffer_width"], surface["buffer_height"]] if surface else None
        )
        if (
            display_state_matches(client, surface, remote, randr)
            and (expected is None or dimensions == expected)
            and (different_from is None or dimensions != different_from)
        ):
            return state
        time.sleep(0.25)
    return state


def connect_desktop(browser, base_url, timeout):
    started = time.monotonic()
    try:
        browser.get(f"{base_url}/workspace/desktop")
    except TimeoutException:
        pass
    wait = WebDriverWait(browser, timeout)
    iframe = wait.until(
        lambda driver: next(
            (
                frame
                for frame in driver.find_elements(By.CSS_SELECTOR, "iframe")
                if frame.get_attribute("name") == "workspace"
                or frame.get_attribute("id") == "workspace-iframe"
            ),
            False,
        )
    )
    browser.switch_to.frame(iframe)
    canvas = wait.until(visible_desktop_canvas)
    html_class = browser.find_element(By.TAG_NAME, "html").get_attribute("class") or ""
    page_identity = f"{browser.title}\n{html_class}\n{browser.page_source[:20000]}".lower()
    if "novnc" in page_identity:
        client = "novnc"
    elif "xpra" in page_identity:
        client = "xpra"
    else:
        client = "unknown"
    wait.until(lambda driver: client_is_connected(driver, client))
    canvas = wait.until(visible_desktop_canvas)
    dimensions = canvas_dimensions(browser, canvas)
    connected_seconds = time.monotonic() - started
    return canvas, client, dimensions, connected_seconds


def check_resize(browser, client, profile, width, height, user):
    resize_timeout = 10 + profile.estimated_rtt_ms / 1000 * 4
    before_state = wait_for_display_state(
        browser, client, user, resize_timeout
    )
    _, before, remote_before, randr_before = before_state
    before_dimensions = (
        [before["buffer_width"], before["buffer_height"]] if before else None
    )
    target_width = max(800, width - 240)
    target_height = max(600, height - 180)
    browser.set_window_size(target_width, target_height)
    resized_state = wait_for_display_state(
        browser,
        client,
        user,
        resize_timeout,
        different_from=before_dimensions,
    )
    _, after, remote_after, randr_after = resized_state
    after_dimensions = (
        [after["buffer_width"], after["buffer_height"]] if after else None
    )
    browser.set_window_size(width, height)
    restored_state = wait_for_display_state(
        browser,
        client,
        user,
        resize_timeout,
        expected=before_dimensions,
    )
    restored_canvas, restored, remote_restored, randr_restored = restored_state
    restored_dimensions = (
        [restored["buffer_width"], restored["buffer_height"]] if restored else None
    )
    nonzero = bool(
        after
        and after["css_width"] > 0
        and after["css_height"] > 0
        and after["buffer_width"] > 0
        and after["buffer_height"] > 0
        and restored
        and restored["css_width"] > 0
        and restored["css_height"] > 0
    )
    remote_resize_confirmed = None
    if client == "xpra":
        remote_resize_confirmed = bool(
            display_state_matches(client, before, remote_before, randr_before)
            and display_state_matches(client, after, remote_after, randr_after)
            and display_state_matches(
                client, restored, remote_restored, randr_restored
            )
            and before_dimensions != after_dimensions
            and restored_dimensions == before_dimensions
        )
    return restored_canvas, {
        "surface_nonzero": nonzero,
        "surface_changed": before != after,
        "remote_resize_confirmed": remote_resize_confirmed,
        "before": before,
        "resized": after,
        "restored": restored,
        "remote_before": remote_before,
        "remote_resized": remote_after,
        "remote_restored": remote_restored,
        "randr_before": randr_before,
        "randr_resized": randr_after,
        "randr_restored": randr_restored,
        "browser_target": {"width": target_width, "height": target_height},
    }


def xpra_clipboard_check(browser, user):
    xclip = workspace_run("command -v xclip || true", user=user).stdout.strip()
    if not xclip:
        return {
            "status": "unsupported",
            "reason": "xclip is not installed in the learner workspace",
        }
    state = browser.execute_script(
        "return typeof client === 'undefined' ? null : "
        "{connected: client.connected, enabled: client.clipboard_enabled, "
        "send_token: typeof client.send_clipboard_token === 'function', "
        "read_buffer: typeof client.get_clipboard_buffer === 'function'};"
    )
    if not state or not all(state.values()):
        return {"status": "unavailable", "client_state": state}
    browser_to_remote = f"browser → workspace ✓ λ {uuid.uuid4().hex}"
    browser.execute_script(
        "Object.defineProperty(navigator, 'clipboard', {"
        "configurable: true, value: {readText: () => Promise.resolve(arguments[0])}"
        "});"
        "client.clipboard_buffer = '';"
        "client.read_clipboard_text();",
        browser_to_remote,
    )
    deadline = time.monotonic() + 10
    remote_value = ""
    while time.monotonic() < deadline:
        remote_value = workspace_run(
            f"DISPLAY=:0 timeout 2 {shlex.quote(xclip)} -selection clipboard -out 2>/dev/null || true",
            user=user,
        ).stdout
        if remote_value == browser_to_remote:
            break
        time.sleep(0.25)
    remote_to_browser = f"workspace → browser ✓ λ {uuid.uuid4().hex}"
    workspace_run(
        f"printf %s {shlex.quote(remote_to_browser)} | DISPLAY=:0 timeout 15 {shlex.quote(xclip)} "
        "-selection clipboard -in >/tmp/desktop-benchmark-xclip.log 2>&1 &",
        user=user,
    )
    try:
        WebDriverWait(browser, 10).until(
            lambda driver: driver.execute_script("return client.get_clipboard_buffer();")
            == remote_to_browser
        )
        browser_value = remote_to_browser
    except TimeoutException:
        browser_value = browser.execute_script("return client.get_clipboard_buffer();")
    browser_to_remote_ok = remote_value == browser_to_remote
    remote_to_browser_ok = browser_value == remote_to_browser
    return {
        "status": "passed" if browser_to_remote_ok and remote_to_browser_ok else "failed",
        "browser_to_workspace": browser_to_remote_ok,
        "workspace_to_browser": remote_to_browser_ok,
    }


def check_clipboard(browser, client, user):
    if client != "xpra":
        return {
            "status": "unsupported",
            "reason": "the harness only exercises Xpra's bidirectional clipboard API",
        }
    try:
        return xpra_clipboard_check(browser, user)
    except Exception as error:
        return {"status": "failed", "error": f"{type(error).__name__}: {error}"}


def client_is_connected(browser, client):
    canvas = visible_desktop_canvas(browser)
    if not canvas:
        return False
    if client == "xpra":
        return bool(
            browser.execute_script(
                "return typeof client !== 'undefined' && client.connected;"
            )
        )
    if client == "novnc":
        html_class = browser.find_element(By.TAG_NAME, "html").get_attribute("class") or ""
        return "noVNC_connected" in html_class.split()
    return True


def check_link_interruption(browser, client, interface, timeout):
    target_interruption_seconds = 2
    ip = shutil.which("ip")
    if not ip:
        return {
            "status": "unsupported",
            "target_interruption_seconds": target_interruption_seconds,
            "reason": "iproute2 is not installed in the disposable client",
        }
    if not pathlib.Path(f"/sys/class/net/{interface}").exists():
        return {
            "status": "unsupported",
            "target_interruption_seconds": target_interruption_seconds,
            "reason": f"interface {interface!r} does not exist",
        }
    ping_token = 1_500_000_000 + uuid.uuid4().int % 500_000_001
    down = subprocess.run(
        [ip, "link", "set", "dev", interface, "down"], capture_output=True, text=True
    )
    if down.returncode:
        return {
            "status": "unsupported",
            "target_interruption_seconds": target_interruption_seconds,
            "reason": f"cannot interrupt {interface}: {down.stderr.strip()}",
        }
    interrupted_at = time.monotonic()
    try:
        time.sleep(target_interruption_seconds)
    finally:
        up = subprocess.run(
            [ip, "link", "set", "dev", interface, "up"], capture_output=True, text=True
        )
    interruption_seconds = time.monotonic() - interrupted_at
    if up.returncode:
        return {
            "status": "failed",
            "target_interruption_seconds": target_interruption_seconds,
            "interruption_seconds": round(interruption_seconds, 3),
            "reason": f"cannot restore {interface}: {up.stderr.strip()}",
        }
    recovery_started_at = time.monotonic()
    try:
        if client == "xpra":
            WebDriverWait(browser, timeout).until(
                lambda driver: driver.execute_script(
                    "if (typeof client === 'undefined') return false;"
                    "if (client.connected && client.last_ping_echoed_time !== arguments[0]) "
                    "client.send(['ping', arguments[0]]);"
                    "return client.connected && client.last_ping_echoed_time === arguments[0];",
                    ping_token,
                )
            )
        else:
            WebDriverWait(browser, timeout).until(
                lambda driver: client_is_connected(driver, client)
            )
        return {
            "status": "pending",
            "target_interruption_seconds": target_interruption_seconds,
            "interruption_seconds": round(interruption_seconds, 3),
            "recovery_probe": (
                "xpra-ping" if client == "xpra" else "client-state-and-later-workload"
            ),
            "recovery_probe_seconds": round(
                time.monotonic() - recovery_started_at, 3
            ),
        }
    except TimeoutException:
        return {
            "status": "failed",
            "target_interruption_seconds": target_interruption_seconds,
            "interruption_seconds": round(interruption_seconds, 3),
            "recovery_probe": (
                "xpra-ping" if client == "xpra" else "client-state-and-later-workload"
            ),
            "recovery_probe_seconds": round(
                time.monotonic() - recovery_started_at, 3
            ),
            "reason": "surface did not recover",
        }


def interface_counters(interface):
    root = pathlib.Path("/sys/class/net") / interface / "statistics"
    try:
        return {
            "rx_bytes": int((root / "rx_bytes").read_text().strip()),
            "tx_bytes": int((root / "tx_bytes").read_text().strip()),
        }
    except FileNotFoundError as error:
        raise RuntimeError(f"cannot read counters for network interface {interface!r}") from error


def counter_delta(before, after):
    return {key: after[key] - before[key] for key in before}


def command_version(*command):
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as error:
        return {
            "command": list(command),
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(error).__name__}: {error}",
        }
    return {
        "command": list(command),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def redacted_invocation(arguments):
    redacted = []
    hide_next = False
    for argument in arguments:
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
        elif argument == "--password":
            redacted.append(argument)
            hide_next = True
        elif argument.startswith("--password="):
            redacted.append("--password=<redacted>")
        else:
            redacted.append(argument)
    return redacted


def benchmark_route(dojo_url, interface):
    hostname = urlparse(dojo_url).hostname
    if not hostname:
        raise RuntimeError(f"cannot determine a host from {dojo_url!r}")
    address = socket.gethostbyname(hostname)
    route = command_version("ip", "route", "get", address)
    if route["returncode"] != 0:
        raise RuntimeError(f"cannot resolve the benchmark route: {route}")
    if f" dev {interface} " not in f" {route['stdout']} ":
        raise RuntimeError(
            f"the route to {address} does not use benchmark interface {interface!r}: {route['stdout']}"
        )
    return {"hostname": hostname, "address": address, **route}


def benchmark_provenance(args):
    benchmark_path = pathlib.Path(__file__).resolve()
    repository = benchmark_path.parent.parent
    git = ["git", "-c", f"safe.directory={repository}", "-C", str(repository)]
    git_head = command_version(*git, "rev-parse", "HEAD")
    git_diff = subprocess.run(
        [*git, "diff", "--binary", "HEAD", "--"],
        capture_output=True,
    )
    git_status = command_version(
        *git, "status", "--short", "--untracked-files=all"
    )
    xpra = workspace_run(
        "xpra --version; readlink -f /run/dojo/bin/dojo-desktop",
        user=args.user,
    )
    return {
        "recorded_unix_seconds": round(time.time(), 3),
        "invocation": [sys.executable, *redacted_invocation(sys.argv)],
        "benchmark_path": str(benchmark_path),
        "benchmark_sha256": hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
        "git_head": git_head["stdout"] if git_head["returncode"] == 0 else git_head,
        "git_tracked_diff_sha256": hashlib.sha256(git_diff.stdout).hexdigest(),
        "git_tracked_diff_returncode": git_diff.returncode,
        "git_status": git_status["stdout"] if git_status["returncode"] == 0 else git_status,
        "firefox": command_version("firefox", "--version"),
        "geckodriver": command_version("geckodriver", "--version"),
        "tc": command_version("tc", "-V"),
        "kernel": platform.uname()._asdict(),
        "route": benchmark_route(args.dojo_url, args.interface),
        "workspace_xpra": {
            "returncode": xpra.returncode,
            "stdout": xpra.stdout.strip(),
            "stderr": xpra.stderr.strip(),
        },
    }


def wait_for_traffic_quiescence(
    interface,
    before,
    timeout,
    shaper=None,
    browser=None,
    delivery_samples=None,
    delivery_started_at=None,
    sample_seconds=0.5,
    quiet_seconds=2,
    quiet_threshold_bytes_per_second=32768,
):
    unmonitored_backlog = {
        "required": False,
        "available": False,
        "empty": True,
        "backlog_bytes": None,
        "queued_packets": None,
        "interfaces": {},
        "reason": "local shaping is not active",
    }
    started = time.monotonic()
    sampled_at = started
    previous = before
    current = before
    last_interval_seconds = 0
    last_interval_bytes = {key: 0 for key in before}
    last_interval_rate = 0
    last_interface_quiet = False
    last_backlog = (
        shaper.backlog_state()
        if shaper
        else unmonitored_backlog
    )
    starting_backlog = last_backlog
    peak_backlog_bytes = last_backlog.get("backlog_bytes") or 0
    peak_queued_packets = last_backlog.get("queued_packets") or 0
    quiet_intervals = 0
    required_quiet_intervals = math.ceil(quiet_seconds / sample_seconds)
    while time.monotonic() - started < timeout:
        time.sleep(sample_seconds)
        if browser and delivery_samples is not None and delivery_started_at is not None:
            sample_browser_delivery(
                browser, delivery_samples, delivery_started_at, "traffic_drain"
            )
        now = time.monotonic()
        current = interface_counters(interface)
        last_interval_seconds = now - sampled_at
        last_interval_bytes = counter_delta(previous, current)
        last_interval_rate = sum(last_interval_bytes.values()) / max(last_interval_seconds, 0.001)
        last_interface_quiet = last_interval_rate <= quiet_threshold_bytes_per_second
        last_backlog = (
            shaper.backlog_state()
            if shaper
            else unmonitored_backlog
        )
        peak_backlog_bytes = max(
            peak_backlog_bytes, last_backlog.get("backlog_bytes") or 0
        )
        peak_queued_packets = max(
            peak_queued_packets, last_backlog.get("queued_packets") or 0
        )
        interval_quiet = last_interface_quiet and last_backlog["empty"]
        quiet_intervals = quiet_intervals + 1 if interval_quiet else 0
        if quiet_intervals >= required_quiet_intervals:
            break
        sampled_at = now
        previous = current
    elapsed = time.monotonic() - started
    return current, {
        "status": "quiesced" if quiet_intervals >= required_quiet_intervals else "timed_out",
        "quiesced": quiet_intervals >= required_quiet_intervals,
        "seconds": round(elapsed, 3),
        "timeout_seconds": timeout,
        "required_quiet_seconds": quiet_seconds,
        "quiet_threshold_bytes_per_second": quiet_threshold_bytes_per_second,
        "quiet_intervals": quiet_intervals,
        "required_quiet_intervals": required_quiet_intervals,
        "last_interval_seconds": round(last_interval_seconds, 3),
        "last_interval_bytes": last_interval_bytes,
        "last_interval_bytes_per_second": round(last_interval_rate, 3),
        "interface_quiet": last_interface_quiet,
        "starting_backlog": starting_backlog,
        "peak_backlog_bytes": peak_backlog_bytes,
        "peak_queued_packets": peak_queued_packets,
        "backlog": last_backlog,
        "bytes": counter_delta(before, current),
    }


def stage_latency_probe(user, sample_count):
    identity = f"latency_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    executable = f"/tmp/dbl_{identity}"
    ready = f"/tmp/dbl_ready_{identity}"
    accepted = f"/tmp/dbl_accepted_{identity}"
    acknowledged = f"/tmp/dbl_ack_{identity}"
    completed = f"/tmp/dbl_completed_{identity}"
    pid_path = f"/tmp/dbl_pid_{identity}"
    log_path = f"/tmp/dbl_log_{identity}"
    total_samples = sample_count + 2
    post_input_guard_seconds = 3
    expected_keys = "xy" + "".join(
        chr(ord("a") + sample_number % 26) for sample_number in range(sample_count)
    )
    script = f"""#!/bin/bash
printf %s "$$" > {pid_path}
stty -echo
trap 'stty echo; printf "\\033[0m\\033[?25h\\033[2J\\033[H"' EXIT
printf '\033[?25l\033[40m\033[2J\033[H'
draw_marker() {{
    read -r terminal_rows terminal_columns < <(stty size)
    marker_row=$((terminal_rows / 2 - 3))
    marker_column=$((terminal_columns / 2 - 8))
    marker_line=0
    marker_output=
    while [ "$marker_line" -lt 6 ]; do
        printf -v marker_segment '\033[%d;%dH\033[48;5;%dm                \033[0m' \
            "$((marker_row + marker_line))" "$marker_column" "$1"
        marker_output+=$marker_segment
        marker_line=$((marker_line + 1))
    done
    printf %s "$marker_output"
}}
state=a
expected_keys={shlex.quote(expected_keys)}
draw_marker 19
printf 0 > {ready}
sample=1
while [ "$sample" -le {total_samples} ]; do
    expected_key=${{expected_keys:$((sample - 1)):1}}
    received_key=
    IFS= read -r -n 1 received_key
    printf '%s:%s' "$sample" "$received_key" > {accepted}
    [ "$received_key" = "$expected_key" ] || exit 2
    if [ "$state" = a ]; then
        state=b
        draw_marker 46
    else
        state=a
        draw_marker 19
    fi
    attempt=0
    while [ "$attempt" -lt 3000 ]; do
        [ "$(cat {acknowledged} 2>/dev/null || true)" = "$sample" ] && break
        attempt=$((attempt + 1))
        sleep 0.01
    done
    printf %s "$sample" > {ready}
    sample=$((sample + 1))
done
received_key=
if IFS= read -r -t {post_input_guard_seconds} -n 1 received_key; then
    printf 'extra:%s' "$received_key" > {accepted}
    exit 2
fi
: > {completed}
sleep 0.5
"""
    encoded = base64.b64encode(script.encode()).decode()
    workspace_run(
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(executable)} && "
        f"chmod 700 {shlex.quote(executable)} && rm -f "
        + " ".join(
            shlex.quote(path)
            for path in (ready, accepted, acknowledged, completed, pid_path, log_path)
        ),
        user=user,
    )
    return executable, ready, accepted, acknowledged, completed, pid_path, log_path


def wait_for_remote_text(user, path, expected, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if read_remote_text(user, path) == expected:
            return True
        time.sleep(0.05)
    return False


def read_remote_text(user, path):
    value = workspace_run(
        f"if [ -e {shlex.quote(path)} ]; then printf present:; "
        f"cat {shlex.quote(path)}; fi",
        user=user,
    ).stdout
    return value.removeprefix("present:") if value.startswith("present:") else None


def remove_latency_probe(user, paths):
    executable, _, _, _, _, pid_path, _ = paths
    workspace_run(
        f"probe_pid=$(cat {shlex.quote(pid_path)} 2>/dev/null || true); "
        "case $probe_pid in ''|*[!0-9]*) probe_pid=;; esac; "
        "if [ -n \"$probe_pid\" ] && [ \"$probe_pid\" -gt 1 ] && "
        "[ -r /proc/$probe_pid/cmdline ] && "
        f"tr '\\0' '\\n' < /proc/$probe_pid/cmdline | grep -Fxq {shlex.quote(executable)}; then "
        "kill -TERM -- $probe_pid 2>/dev/null || true; "
        "fi; "
        "rm -f " + " ".join(shlex.quote(path) for path in paths),
        user=user,
    )


def measure_interaction_latency(
    browser,
    canvas,
    profile,
    user,
    interface,
    shaper,
    shaping,
    sample_count,
):
    timeout = 15 + profile.estimated_rtt_ms / 1000 * 8
    paths = stage_latency_probe(user, sample_count)
    executable, ready, accepted, acknowledged, completed, _, log_path = paths
    samples = []
    calibration = []
    try:
        ActionChains(browser).move_to_element(canvas).click().perform()
        workspace_run(
            "DISPLAY=:0 xfce4-terminal --disable-server --fullscreen --hide-menubar "
            "--hide-toolbar --hide-scrollbar "
            f"--command={shlex.quote(executable)} >{shlex.quote(log_path)} 2>&1 &",
            user=user,
        )
        if not wait_for_remote_text(user, ready, "0", timeout):
            raise TimeoutException("latency probe did not become ready")
        canvas = WebDriverWait(browser, timeout).until(visible_desktop_canvas)
        before = interface_counters(interface)
        _, quiescence = wait_for_traffic_quiescence(
            interface,
            before,
            timeout,
            shaper=shaper if shaping == "local" else None,
            sample_seconds=0.1,
            quiet_seconds=0.5,
        )
        if not quiescence["quiesced"]:
            raise TimeoutException("traffic did not quiesce before latency calibration")
        ActionChains(browser).move_to_element(canvas).click().perform()
        time.sleep(0.25)
        calibration.append(capture_latency_template(browser, canvas, "a"))
        previous_color = canvas_region_rgb(browser, canvas)
        for calibration_number, template_name, key in (
            (1, "b", "x"),
            (2, "a", "y"),
        ):
            ActionChains(browser).send_keys(key).perform()
            accepted_value = f"{calibration_number}:{key}"
            if not wait_for_remote_text(user, accepted, accepted_value, timeout):
                raise TimeoutException(
                    f"latency calibration {calibration_number} expected {accepted_value!r}, "
                    f"observed {read_remote_text(user, accepted)!r}"
                )
            previous_color = wait_for_canvas_region_transition(
                browser, canvas, previous_color, timeout
            )
            before = interface_counters(interface)
            _, quiescence = wait_for_traffic_quiescence(
                interface,
                before,
                timeout,
                shaper=shaper if shaping == "local" else None,
                sample_seconds=0.1,
                quiet_seconds=0.5,
            )
            if not quiescence["quiesced"]:
                raise TimeoutException(
                    f"traffic did not quiesce during latency calibration {calibration_number}"
                )
            template = capture_latency_template(browser, canvas, template_name)
            calibration.append(template)
            if template["discriminating_pixels"] < 32:
                raise RuntimeError(
                    f"latency calibration found only {template['discriminating_pixels']} discriminating pixels"
                )
            workspace_run(
                f"printf %s {calibration_number} > {shlex.quote(acknowledged)}",
                user=user,
            )
        for sample_number in range(1, sample_count + 1):
            remote_sample = sample_number + 2
            ready_value = str(remote_sample - 1)
            if not wait_for_remote_text(user, ready, ready_value, timeout):
                raise TimeoutException(
                    f"latency probe sample {sample_number} did not become ready"
                )
            canvas = WebDriverWait(browser, timeout).until(visible_desktop_canvas)
            target_name = "b" if remote_sample % 2 else "a"
            source_name = "a" if target_name == "b" else "b"
            wait_for_latency_template(
                browser, canvas, target_name, source_name, timeout
            )
            jitter_seconds = 0.6 + ((sample_number * 37 + remote_sample * 13) % 41) / 100
            time.sleep(jitter_seconds)
            before = interface_counters(interface)
            _, quiescence = wait_for_traffic_quiescence(
                interface,
                before,
                timeout,
                shaper=shaper if shaping == "local" else None,
                sample_seconds=0.1,
                quiet_seconds=0.5,
            )
            if not quiescence["quiesced"]:
                raise TimeoutException(
                    f"traffic did not quiesce before latency sample {sample_number}"
                )
            key = chr(ord("a") + (sample_number - 1) % 26)
            accepted_value = f"{remote_sample}:{key}"
            armed = arm_canvas_latency_probe(
                browser,
                canvas,
                key,
                source_name,
                target_name,
                timeout,
            )
            if not isinstance(armed.get("initial_progress"), (int, float)) or abs(
                armed["initial_progress"]
            ) > 0.05:
                raise RuntimeError(
                    f"latency probe source template was not stable: {armed}"
                )
            ActionChains(browser).send_keys(key).perform()
            try:
                state = WebDriverWait(browser, timeout, poll_frequency=0.01).until(
                    lambda driver: (
                        current
                        if (current := canvas_latency_probe_state(driver))
                        and current.get("status")
                        in ("passed", "failed", "timed_out", "untrusted_input")
                        else False
                    )
                )
            except TimeoutException:
                state = canvas_latency_probe_state(browser) or {"status": "timed_out"}
            remote_input_accepted = wait_for_remote_text(
                user, accepted, accepted_value, timeout
            )
            for endpoint in ("onset", "settled"):
                if state.get(endpoint):
                    state[endpoint] = {
                        key: round(value, 3)
                        for key, value in state[endpoint].items()
                    }
            state["raf_intervals_ms"] = [
                round(value, 3) for value in state.get("raf_intervals_ms", [])
            ]
            state.update(
                {
                    "sample": sample_number,
                    "expected_key": key,
                    "remote_input_observed": read_remote_text(user, accepted),
                    "remote_input_accepted": remote_input_accepted,
                    "pre_input_delay_ms": round(jitter_seconds * 1000, 3),
                    "pre_input_quiescence_seconds": quiescence["seconds"],
                }
            )
            if state.get("status") != "passed" or not remote_input_accepted:
                samples.append(state)
                raise RuntimeError(f"latency probe sample failed: {state}")
            samples.append(state)
            workspace_run(
                f"printf %s {remote_sample} > {shlex.quote(acknowledged)}",
                user=user,
            )
        if not wait_for_remote_text(user, completed, "", timeout):
            raise TimeoutException(
                "latency probe did not complete after the post-input guard; "
                f"observed {read_remote_text(user, accepted)!r}"
            )
        onset_values = [sample["onset"]["upper_ms"] for sample in samples]
        settled_values = [sample["settled"]["upper_ms"] for sample in samples]
        raf_intervals = [
            interval
            for sample in samples
            for interval in sample["raf_intervals_ms"]
        ]
        return {
            "status": "passed",
            "method": "trusted-browser-keydown-to-requestAnimationFrame-observed-calibrated-marker-change",
            "clock": "KeyboardEvent.timeStamp and performance.now after requestAnimationFrame canvas reads",
            "sample_grid": "192x108 RGB",
            "template_pixel_l1_threshold": 48,
            "minimum_discriminating_pixels": 32,
            "onset_progress_threshold": 0.10,
            "settled_progress_threshold": 0.90,
            "warmup_samples": 2,
            "remote_input_validation": "exact expected ASCII key and sample sequence",
            "post_input_guard_seconds": 3,
            "measurement_phase": "same connected session before link interruption and screen-update workload",
            "requested_samples": sample_count,
            "calibration": calibration,
            "samples": samples,
            "onset_upper_ms": numeric_summary(onset_values),
            "settled_upper_ms": numeric_summary(settled_values),
            "raf_interval_ms": numeric_summary(raf_intervals),
        }
    except Exception as error:
        return {
            "status": "failed",
            "method": "trusted-browser-keydown-to-requestAnimationFrame-observed-calibrated-marker-change",
            "remote_input_validation": "exact expected ASCII key and sample sequence",
            "post_input_guard_seconds": 3,
            "measurement_phase": "same connected session before link interruption and screen-update workload",
            "requested_samples": sample_count,
            "calibration": calibration,
            "samples": samples,
            "error": f"{type(error).__name__}: {error}",
        }
    finally:
        with contextlib.suppress(Exception):
            browser.execute_script(
                "if (window.__dojoLatencyStop) window.__dojoLatencyStop();"
            )
        with contextlib.suppress(Exception):
            workspace_run(
                f"printf done > {shlex.quote(acknowledged)}",
                user=user,
            )
        with contextlib.suppress(Exception):
            remove_latency_probe(user, paths)


def stage_workload(user, profile_name, seconds):
    identity = f"{profile_name}_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    executable = f"/tmp/dbw_{identity}"
    started = f"/tmp/dbw_started_{identity}"
    completed = f"/tmp/dbw_completed_{identity}"
    pid_path = f"/tmp/dbw_pid_{identity}"
    frames = seconds * 10
    script = f"""#!/bin/bash
printf %s "$$" > {pid_path}
: > {started}
printf '\\033[2J'
frame=0
while [ \"$frame\" -lt {frames} ]; do
    printf '\\033[H'
    row=0
    while [ \"$row\" -lt 24 ]; do
        color=$((16 + (frame * 7 + row * 13) % 216))
        printf '\\033[48;5;%dm frame=%04d row=%02d 0123456789abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMN \\033[0m\\n' \"$color\" \"$frame\" \"$row\"
        row=$((row + 1))
    done
    frame=$((frame + 1))
    sleep 0.1
done
: > {completed}
sleep 1
"""
    encoded = base64.b64encode(script.encode()).decode()
    workspace_run(
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(executable)} && "
        f"chmod 700 {shlex.quote(executable)} && "
        f"rm -f {shlex.quote(started)} {shlex.quote(completed)} {shlex.quote(pid_path)}",
        user=user,
    )
    return executable, started, completed, pid_path


def wait_for_remote_file(
    user,
    path,
    timeout,
    browser=None,
    delivery_samples=None,
    delivery_started_at=None,
    delivery_phase="workload",
):
    deadline = time.monotonic() + timeout
    while True:
        if browser and delivery_samples is not None and delivery_started_at is not None:
            sample_browser_delivery(
                browser, delivery_samples, delivery_started_at, delivery_phase
            )
        result = workspace_run(
            f"test -e {shlex.quote(path)} && printf yes || true",
            user=user,
        )
        if result.stdout == "yes":
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.5, remaining))


def prepare_workload(browser, profile, user):
    workspace_run(
        "DISPLAY=:0 xfce4-terminal --disable-server >/tmp/desktop-benchmark-terminal.log 2>&1 &",
        user=user,
    )
    time.sleep(2 + profile.estimated_rtt_ms / 1000)
    return WebDriverWait(browser, 10).until(visible_desktop_canvas)


def start_workload(browser, canvas, executable):
    ActionChains(browser).move_to_element(canvas).click().send_keys(
        f"exec setsid --wait {shlex.quote(executable)}"
    ).send_keys(Keys.ENTER).perform()


def remove_workload(user, paths):
    executable, _, _, pid_path = paths
    workspace_run(
        f"rm -f {shlex.quote(executable)}; "
        "workload_matches() { "
        f"workload_pid=$(cat {shlex.quote(pid_path)} 2>/dev/null || true); "
        "case $workload_pid in ''|*[!0-9]*) return 1;; esac; "
        "test -r /proc/$workload_pid/cmdline && "
        f"tr '\\0' '\\n' < /proc/$workload_pid/cmdline | grep -Fxq {shlex.quote(executable)} && "
        "test \"$(ps -o pgid= -p $workload_pid | tr -d ' ')\" = \"$workload_pid\"; "
        "}; "
        "term_sent=0; "
        "for attempt in 1 2 3 4 5; do "
        "if workload_matches && test $term_sent -eq 0; then "
        "kill -TERM -- -$workload_pid 2>/dev/null || true; term_sent=1; "
        "fi; "
        "sleep 0.1; "
        "done; "
        "if workload_matches; then kill -KILL -- -$workload_pid 2>/dev/null || true; fi; "
        "rm -f " + " ".join(shlex.quote(path) for path in paths),
        user=user,
    )


def save_screenshot(browser, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    browser.switch_to.default_content()
    if not browser.save_screenshot(str(path)) or not path.is_file():
        raise RuntimeError(f"failed to save screenshot {path}")
    frames = browser.find_elements(By.CSS_SELECTOR, "iframe")
    workspace_frame = next(
        (
            frame
            for frame in frames
            if frame.get_attribute("name") == "workspace"
            or frame.get_attribute("id") == "workspace-iframe"
        ),
        None,
    )
    if workspace_frame:
        browser.switch_to.frame(workspace_frame)


def measure_profile(args, profile, repetition, trial_index, output_dir, shaper):
    result = {
        "profile": asdict(profile),
        "repetition": repetition,
        "trial_index": trial_index,
        "estimated_rtt_ms": profile.estimated_rtt_ms,
        "shaping": args.shaping,
        "pre_workload_quiescence": {
            "status": "not_attempted",
            "quiesced": False,
            "reason": "workload setup not reached",
        },
    }
    browser = None
    workload_paths = None
    try:
        browser = make_browser(args.width, args.height, args.page_load_timeout)
        browser_login(browser, args.dojo_url, args.user, args.password)
        if args.shaping == "local":
            shaper.apply(profile)
        elif args.shaping == "none" and profile.name != "clean":
            raise ShapingUnavailable("--shaping none is valid only for the clean profile")
        result["shaping_state"] = shaper.describe()
        connect_before = interface_counters(args.interface)
        canvas, client, dimensions, connect_seconds = connect_desktop(
            browser, args.dojo_url, args.connect_timeout
        )
        connect_after = interface_counters(args.interface)
        result.update(
            {
                "connected": True,
                "client": client,
                "canvas": dimensions,
                "connect_seconds": round(connect_seconds, 3),
                "connect_bytes": counter_delta(connect_before, connect_after),
                "desktop_route": benchmark_route(
                    browser.execute_script("return window.location.href;"),
                    args.interface,
                ),
            }
        )
        if args.variant != "auto" and client != args.variant:
            raise RuntimeError(f"expected {args.variant}, detected {client}")
        if client == "unknown":
            raise RuntimeError("could not identify the desktop client")
        result["frameless"] = desktop_is_frameless(browser, client)
        if not result["frameless"]:
            raise RuntimeError("desktop client added its own window frame")
        canvas, resize = check_resize(
            browser, client, profile, args.width, args.height, args.user
        )
        result["resize"] = resize
        result["clipboard"] = check_clipboard(browser, client, args.user)
        if client == "xpra" and result["clipboard"].get("status") != "passed":
            raise RuntimeError(f"Xpra clipboard check did not pass: {result['clipboard']}")
        time.sleep(args.settle_seconds)
        repetition_suffix = f"r{repetition:02d}"
        connected_screenshot = (
            output_dir / f"{args.label}-{profile.name}-{repetition_suffix}-connected.png"
        )
        save_screenshot(browser, connected_screenshot)
        result["connected_screenshot"] = str(connected_screenshot)
        canvas = visible_desktop_canvas(browser)
        if not canvas:
            raise RuntimeError("desktop surface disappeared before the latency probe")
        result["interaction_latency"] = measure_interaction_latency(
            browser,
            canvas,
            profile,
            args.user,
            args.interface,
            shaper,
            args.shaping,
            args.latency_samples,
        )
        if result["interaction_latency"].get("status") != "passed":
            raise RuntimeError(
                f"interaction latency check did not pass: {result['interaction_latency']}"
            )
        if args.check_link_interruption:
            result["link_interruption"] = check_link_interruption(
                browser, client, args.interface, args.connect_timeout
            )
            canvas = visible_desktop_canvas(browser)
            if not canvas:
                raise RuntimeError("desktop surface disappeared after the link interruption")
        else:
            result["link_interruption"] = {"status": "skipped"}
        workload_paths = stage_workload(args.user, profile.name, args.workload_seconds)
        executable, started_marker, completed_marker, _ = workload_paths
        canvas = prepare_workload(browser, profile, args.user)
        pre_workload_started = interface_counters(args.interface)
        workload_before, pre_workload_quiescence = wait_for_traffic_quiescence(
            args.interface,
            pre_workload_started,
            args.quiescence_timeout + profile.estimated_rtt_ms / 1000 * 4,
            shaper=shaper if args.shaping == "local" else None,
        )
        result["pre_workload_quiescence"] = pre_workload_quiescence
        if not pre_workload_quiescence["quiesced"]:
            raise RuntimeError(
                f"desktop traffic did not quiesce before the workload: {pre_workload_quiescence}"
            )
        workload_started_at = time.monotonic()
        delivery_samples = []
        sample_browser_delivery(
            browser, delivery_samples, workload_started_at, "baseline"
        )
        start_workload(browser, canvas, executable)
        input_timeout = 15 + profile.estimated_rtt_ms / 1000 * 4
        input_accepted = wait_for_remote_file(
            args.user,
            started_marker,
            input_timeout,
            browser,
            delivery_samples,
            workload_started_at,
            "input_wait",
        )
        result["input_accepted"] = input_accepted
        if input_accepted:
            workload_screenshot_at = time.monotonic() + min(
                10, max(1, args.workload_seconds // 3)
            )
            sample_browser_delivery_until(
                browser,
                delivery_samples,
                workload_started_at,
                "workload",
                workload_screenshot_at,
            )
            workload_screenshot = (
                output_dir / f"{args.label}-{profile.name}-{repetition_suffix}-workload.png"
            )
            save_screenshot(browser, workload_screenshot)
            result["workload_screenshot"] = str(workload_screenshot)
            result["workload_screenshot_seconds"] = round(
                time.monotonic() - workload_started_at, 3
            )
            remaining_timeout = args.workload_seconds + 20 + profile.estimated_rtt_ms / 1000 * 4
            workload_complete = wait_for_remote_file(
                args.user,
                completed_marker,
                remaining_timeout,
                browser,
                delivery_samples,
                workload_started_at,
                "workload",
            )
        else:
            workload_complete = False
        workload_generation_seconds = time.monotonic() - workload_started_at
        workload_generated_after = interface_counters(args.interface)
        if workload_complete:
            workload_after, traffic_drain = wait_for_traffic_quiescence(
                args.interface,
                workload_generated_after,
                args.quiescence_timeout + profile.estimated_rtt_ms / 1000 * 4,
                shaper=shaper if args.shaping == "local" else None,
                browser=browser,
                delivery_samples=delivery_samples,
                delivery_started_at=workload_started_at,
            )
        else:
            sample_browser_delivery(
                browser, delivery_samples, workload_started_at, "incomplete"
            )
            workload_after = workload_generated_after
            traffic_drain = {
                "status": "not_attempted",
                "quiesced": False,
                "seconds": 0,
                "backlog": (
                    shaper.backlog_state()
                    if args.shaping == "local"
                    else {
                        "required": False,
                        "available": False,
                        "empty": True,
                        "backlog_bytes": None,
                        "queued_packets": None,
                        "interfaces": {},
                        "reason": "local shaping is not active",
                    }
                ),
                "bytes": {key: 0 for key in workload_generated_after},
            }
        workload_seconds = time.monotonic() - workload_started_at
        workload_bytes = counter_delta(workload_before, workload_after)
        browser_delivery = summarize_browser_delivery(delivery_samples)
        result.update(
            {
                "workload_complete": workload_complete,
                "browser_delivery": browser_delivery,
                "workload_generation_seconds": round(workload_generation_seconds, 3),
                "traffic_drain": traffic_drain,
                "workload_seconds": round(workload_seconds, 3),
                "workload_bytes": workload_bytes,
                "workload_rx_kbps": round(
                    workload_bytes["rx_bytes"] * 8 / max(workload_seconds, 0.001) / 1000, 3
                ),
                "workload_tx_kbps": round(
                    workload_bytes["tx_bytes"] * 8 / max(workload_seconds, 0.001) / 1000, 3
                ),
            }
        )
        if result.get("link_interruption", {}).get("status") == "pending":
            result["link_interruption"]["status"] = (
                "passed"
                if input_accepted
                and workload_complete
                and browser_delivery["status"] == "passed"
                else "failed"
            )
            result["link_interruption"]["remote_input_after_interruption"] = input_accepted
            result["link_interruption"]["workload_after_interruption"] = workload_complete
            result["link_interruption"]["browser_delivery_after_interruption"] = (
                browser_delivery["status"] == "passed"
            )
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        result.setdefault("connected", False)
        result.setdefault("input_accepted", False)
        result.setdefault("workload_complete", False)
        if browser:
            with contextlib.suppress(Exception):
                error_screenshot = (
                    output_dir / f"{args.label}-{profile.name}-r{repetition:02d}-error.png"
                )
                save_screenshot(browser, error_screenshot)
                result["error_screenshot"] = str(error_screenshot)
    finally:
        if browser:
            with contextlib.suppress(Exception):
                browser.quit()
        if workload_paths:
            with contextlib.suppress(Exception):
                remove_workload(args.user, workload_paths)
        if args.shaping == "local":
            shaper.cleanup()
    return result


def percentile(values, quantile):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def numeric_summary(values):
    if not values:
        return {"count": 0, "median": None, "min": None, "max": None, "p95": None}
    return {
        "count": len(values),
        "median": round(statistics.median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "p95": round(percentile(values, 0.95), 3),
    }


def metric_summary(results, value):
    values = [number for result in results if isinstance((number := value(result)), (int, float))]
    return numeric_summary(values)


def boolean_pass_count(results, value):
    return {
        "passed": sum(bool(value(result)) for result in results),
        "attempted": len(results),
    }


def status_pass_count(results, key):
    statuses = [result.get(key, {}).get("status") for result in results]
    attempted = [status for status in statuses if status in ("passed", "failed")]
    return {
        "passed": attempted.count("passed"),
        "attempted": len(attempted),
        "skipped": len(statuses) - len(attempted),
    }


def latency_sample_summary(results, endpoint):
    values = []
    for result in results:
        interaction_latency = result.get("interaction_latency", {})
        if interaction_latency.get("status") != "passed":
            continue
        for sample in interaction_latency.get("samples", []):
            endpoint_value = sample.get(endpoint)
            if isinstance(endpoint_value, dict) and isinstance(
                endpoint_value.get("upper_ms"), (int, float)
            ):
                values.append(endpoint_value["upper_ms"])
    return numeric_summary(values)


def successful_workload_results(results):
    return [
        result
        for result in results
        if result.get("input_accepted")
        and result.get("workload_complete")
        and result.get("pre_workload_quiescence", {}).get("quiesced")
        and result.get("browser_delivery", {}).get("status") == "passed"
        and result.get("traffic_drain", {}).get("quiesced")
    ]


def summarize_group(results):
    workload_results = successful_workload_results(results)
    return {
        "trials": len(results),
        "errors": sum("error" in result for result in results),
        "metrics": {
            "connect_seconds": metric_summary(results, lambda result: result.get("connect_seconds")),
            "connect_rx_bytes": metric_summary(
                results, lambda result: result.get("connect_bytes", {}).get("rx_bytes")
            ),
            "connect_tx_bytes": metric_summary(
                results, lambda result: result.get("connect_bytes", {}).get("tx_bytes")
            ),
            "link_interruption_seconds": metric_summary(
                results,
                lambda result: result.get("link_interruption", {}).get(
                    "interruption_seconds"
                ),
            ),
            "link_recovery_probe_seconds": metric_summary(
                results,
                lambda result: result.get("link_interruption", {}).get(
                    "recovery_probe_seconds"
                ),
            ),
            "interaction_onset_upper_ms": latency_sample_summary(
                results, "onset"
            ),
            "interaction_settled_upper_ms": latency_sample_summary(
                results, "settled"
            ),
            "pre_workload_quiescence_seconds": metric_summary(
                results,
                lambda result: result.get("pre_workload_quiescence", {}).get(
                    "seconds"
                ),
            ),
            "workload_generation_seconds": metric_summary(
                workload_results, lambda result: result.get("workload_generation_seconds")
            ),
            "traffic_drain_seconds": metric_summary(
                workload_results, lambda result: result.get("traffic_drain", {}).get("seconds")
            ),
            "workload_seconds": metric_summary(
                workload_results, lambda result: result.get("workload_seconds")
            ),
            "workload_rx_bytes": metric_summary(
                workload_results, lambda result: result.get("workload_bytes", {}).get("rx_bytes")
            ),
            "workload_tx_bytes": metric_summary(
                workload_results, lambda result: result.get("workload_bytes", {}).get("tx_bytes")
            ),
            "workload_rx_kbps": metric_summary(
                workload_results, lambda result: result.get("workload_rx_kbps")
            ),
            "workload_tx_kbps": metric_summary(
                workload_results, lambda result: result.get("workload_tx_kbps")
            ),
        },
        "functional_pass_counts": {
            "connected": boolean_pass_count(results, lambda result: result.get("connected")),
            "frameless": boolean_pass_count(results, lambda result: result.get("frameless")),
            "resize": boolean_pass_count(
                results,
                lambda result: result.get("resize", {}).get("surface_nonzero")
                and result.get("resize", {}).get("surface_changed")
                and result.get("resize", {}).get("remote_resize_confirmed") is not False,
            ),
            "clipboard": status_pass_count(results, "clipboard"),
            "link_interruption": status_pass_count(results, "link_interruption"),
            "interaction_latency": status_pass_count(
                results, "interaction_latency"
            ),
            "pre_workload_quiesced": boolean_pass_count(
                results,
                lambda result: result.get("pre_workload_quiescence", {}).get(
                    "quiesced"
                ),
            ),
            "input_accepted": boolean_pass_count(
                results, lambda result: result.get("input_accepted")
            ),
            "workload_complete": boolean_pass_count(
                results, lambda result: result.get("workload_complete")
            ),
            "browser_delivery": status_pass_count(results, "browser_delivery"),
            "traffic_quiesced": boolean_pass_count(
                results, lambda result: result.get("traffic_drain", {}).get("quiesced")
            ),
        },
    }


def summarize_results(results, profile_names):
    return {
        "overall": summarize_group(results),
        "profiles": {
            name: summarize_group(
                [result for result in results if result.get("profile", {}).get("name") == name]
            )
            for name in profile_names
        },
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Measure the HTML desktop client from a disposable Firefox client.",
        allow_abbrev=False,
        epilog=(
            "Run this from a disposable dojo-test container with the repository and Docker socket mounted. "
            "Each degraded profile applies the same delay, loss, and rate cap in both directions. "
            "Local degraded profiles require iproute2, --cap-add NET_ADMIN, and kernel IFB support. "
            "When IFB is unavailable, shape the client container's host peer and invoke one profile at a "
            "time with --shaping external."
        ),
    )
    parser.add_argument("--user", default=os.getenv("DESKTOP_BENCHMARK_USER"))
    parser.add_argument("--password", default=os.getenv("DESKTOP_BENCHMARK_PASSWORD"))
    parser.add_argument("--dojo-url", default=DOJO_URL.rstrip("/"))
    parser.add_argument("--profiles", default="clean,wan,mobile,poor")
    parser.add_argument("--variant", choices=("auto", "novnc", "xpra"), default="auto")
    parser.add_argument("--shaping", choices=("local", "external", "none"), default="local")
    parser.add_argument("--interface", default="eth0")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--label", default="desktop")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--connect-timeout", type=int, default=180)
    parser.add_argument("--page-load-timeout", type=int, default=180)
    parser.add_argument("--settle-seconds", type=int, default=3)
    parser.add_argument("--workload-seconds", type=int, default=30)
    parser.add_argument("--latency-samples", type=int, default=20)
    parser.add_argument("--quiescence-timeout", type=int, default=30)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--check-link-interruption",
        "--check-reconnect",
        dest="check_link_interruption",
        action="store_true",
        help="interrupt the client interface for two seconds and verify end-to-end recovery",
    )
    args = parser.parse_args()
    if not args.user or not args.password:
        parser.error("--user and --password are required, or set their DESKTOP_BENCHMARK_* variables")
    try:
        args.profile_names = [name.strip() for name in args.profiles.split(",") if name.strip()]
        if not args.profile_names:
            parser.error("--profiles must select at least one profile")
        unknown = [name for name in args.profile_names if name not in PROFILES]
        if unknown:
            parser.error(f"unknown profiles: {', '.join(unknown)}")
    except ValueError as error:
        parser.error(str(error))
    if args.shaping == "external" and len(args.profile_names) != 1:
        parser.error("--shaping external requires exactly one selected profile")
    if args.workload_seconds < 1:
        parser.error("--workload-seconds must be positive")
    if args.latency_samples < 1:
        parser.error("--latency-samples must be positive")
    if args.quiescence_timeout < 1:
        parser.error("--quiescence-timeout must be positive")
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    return args


def write_json(path, value):
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(json.dumps(value, indent=2) + "\n")
    temporary_path.replace(path)


def main():
    args = parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    warm_desktop(args.dojo_url, args.user, args.password)
    provenance = benchmark_provenance(args)
    shaper = LocalLinkShaper(args.interface)
    results = []
    trials_path = args.output / f"{args.label}-trials.json"
    shaping_unavailable = False
    trial_index = 0
    try:
        for repetition in range(1, args.repetitions + 1):
            offset = (repetition - 1) % len(args.profile_names)
            profile_order = args.profile_names[offset:] + args.profile_names[:offset]
            for name in profile_order:
                trial_index += 1
                result = measure_profile(
                    args,
                    PROFILES[name],
                    repetition,
                    trial_index,
                    args.output,
                    shaper,
                )
                results.append(result)
                write_json(trials_path, results)
                print(json.dumps(result, indent=2), flush=True)
                if isinstance(result.get("error"), str) and result["error"].startswith(
                    "ShapingUnavailable:"
                ):
                    shaping_unavailable = True
                    break
            if shaping_unavailable:
                break
    finally:
        shaper.cleanup()
    report = {
        "label": args.label,
        "dojo_url": args.dojo_url,
        "variant": args.variant,
        "interface": args.interface,
        "workload_seconds": args.workload_seconds,
        "latency_samples": args.latency_samples,
        "repetitions": args.repetitions,
        "profile_ordering": "cyclic-rotation-by-repetition",
        "check_link_interruption": args.check_link_interruption,
        "profiles": {
            name: asdict(PROFILES[name]) for name in args.profile_names
        },
        "methodology": {
            "connect_interval": "authenticated desktop navigation to connected client and visible canvas",
            "workload": (
                f"{args.workload_seconds * 10} shell-generated terminal screen updates, "
                "24 rows per update"
            ),
            "traffic_interval": (
                "client-interface RX/TX counter delta from input start through the first "
                "qualifying two-second quiet window with empty local netem queues"
            ),
            "browser_delivery": "distinct sampled post-input canvas states",
            "interaction_latency": (
                "trusted browser keydown to the first requestAnimationFrame-observed 10% and 90% "
                "transitions toward a calibrated remote terminal marker; reported values are the "
                "conservative upper bounds of the observation intervals, measured on the same "
                "connected session before link interruption and the screen-update workload"
            ),
            "screenshots": "qualitative captures",
        },
        "provenance": provenance,
        "results": results,
        "summary": summarize_results(results, args.profile_names),
    }
    report_path = args.output / f"{args.label}-results.json"
    write_json(report_path, report)
    summary_path = args.output / f"{args.label}-summary.json"
    summary_report = {
        key: value for key, value in report.items() if key != "results"
    }
    write_json(summary_path, summary_report)
    print(f"wrote {report_path}")
    print(f"wrote {summary_path}")
    return 0 if results and all(
        result.get("connected")
        and result.get("client") in ("novnc", "xpra")
        and result.get("frameless")
        and result.get("pre_workload_quiescence", {}).get("quiesced")
        and result.get("input_accepted")
        and result.get("workload_complete")
        and result.get("browser_delivery", {}).get("status") == "passed"
        and result.get("interaction_latency", {}).get("status") == "passed"
        and result.get("traffic_drain", {}).get("quiesced")
        and result.get("resize", {}).get("surface_nonzero")
        and result.get("resize", {}).get("surface_changed")
        and result.get("resize", {}).get("remote_resize_confirmed") is not False
        and (
            result.get("client") != "xpra"
            or result.get("clipboard", {}).get("status") == "passed"
        )
        and (
            not args.check_link_interruption
            or result.get("link_interruption", {}).get("status") == "passed"
        )
        for result in results
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
