"""Capture screenshots of each SpectroForge view using Playwright."""
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, Page


BASE = "http://localhost:8744"
OUT = Path(__file__).parent.parent / "assets" / "screenshots"
EXAMPLES = (Path(__file__).parent.parent.parent / "examples").resolve() / "hmsa-2021"
DEFAULT_INSTRUMENT_TOML = EXAMPLES / "HiTMIS-A 2021-instrument.toml"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1400, 900


class ScreenshotPreview:
    """Simple Tk preview window that updates after each captured screenshot."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._tk = None
        self._root = None
        self._label = None
        self._img = None
        self._warned = False
        if not enabled:
            return
        try:
            import tkinter as tk

            self._tk = tk
            self._root = tk.Tk()
            self._root.title("Screenshot Preview")
            self._label = tk.Label(
                self._root, text="Waiting for first screenshot...")
            self._label.pack()
            self._root.update_idletasks()
            self._root.update()
        except Exception as exc:
            self.enabled = False
            print(f"Warning: screenshot preview disabled ({exc}).")

    def show(self, image_path: Path) -> None:
        if not self.enabled or self._root is None or self._label is None or self._tk is None:
            return
        try:
            self._img = self._tk.PhotoImage(file=str(image_path))
            self._label.configure(image=self._img, text="")
            self._root.title(f"Screenshot Preview: {image_path.name}")
            self._root.deiconify()
            self._root.lift()
            self._root.update_idletasks()
            self._root.update()
        except Exception as exc:
            if not self._warned:
                print(f"Warning: failed to preview screenshot ({exc}).")
                self._warned = True

    def close(self) -> None:
        if self._root is None:
            return
        try:
            self._root.destroy()
        except Exception:
            pass


def save_screenshot(page: Page, out: Path, filename: str, state: dict, full_page: bool = True) -> None:
    """Capture screenshot and refresh preview window."""
    path = out / filename
    page.screenshot(path=str(path), full_page=full_page)
    preview = state.get("preview")
    if preview is not None:
        preview.show(path)


def capture_step(page: Page, state: dict | None, label: str) -> None:
    """Capture a step-by-step trace screenshot for UI actions and transitions."""
    if not state or not state.get("step_captures", False):
        return
    out = state.get("step_out")
    if out is None:
        return
    state["step_index"] = int(state.get("step_index", 0)) + 1
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", label.strip().lower()).strip("-")
    if not safe:
        safe = "step"
    filename = f"{state['step_index']:04d}-{safe}.png"
    save_screenshot(page, out, filename, state)


def page_fetch(page: Page, path: str, payload: dict) -> dict:
    """POST JSON via fetch inside the browser page (same session)."""
    return page.evaluate(
        """
        async ([path, payload]) => {
            const r = await fetch(path, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            return r.ok ? await r.json() : { _error: r.status, _body: await r.text() };
        }
        """,
        [path, payload],
    )


def page_get(page: Page, path: str) -> dict:
    """GET via fetch inside the browser page."""
    return page.evaluate(
        """
        async ([path]) => {
            const r = await fetch(path);
            return r.ok ? await r.json() : { _error: r.status };
        }
        """,
        [path],
    )


def load_instrument_toml(page: Page, state: dict | None = None) -> None:
    """Load the example HiTMIS TOML via the Menu > Load button and file chooser."""
    toml_path = DEFAULT_INSTRUMENT_TOML if DEFAULT_INSTRUMENT_TOML.exists(
    ) else next(EXAMPLES.glob("*.toml"))
    print(f"Loading TOML via UI: {toml_path.name}")
    capture_step(page, state, "toml-before-menu-click")
    # Open the "Menu" to reveal the hidden load button
    page.get_by_role("button", name="Menu", exact=False).first.click()
    page.wait_for_timeout(500)
    capture_step(page, state, "toml-menu-opened")
    with page.expect_file_chooser() as fc_info:
        page.locator("#loadInstrumentTomlBtn").click()
    file_chooser = fc_info.value
    file_chooser.set_files(str(toml_path))
    print("TOML file submitted via file chooser.")
    capture_step(page, state, "toml-file-selected")


def upload_night_image(page: Page, state: dict | None = None) -> None:
    """Upload the night image via the UI file input (triggers frontend state update)."""
    img_path = next(EXAMPLES.glob("hitmis_2021_night.png"))
    dismiss_error_dialog(page, state)
    capture_step(page, state, "straighten-before-upload-click")
    # Click "Upload New Image" button, then intercept the file chooser
    with page.expect_file_chooser() as fc_info:
        page.get_by_role("button", name="Upload New Image",
                         exact=False).click()
    file_chooser = fc_info.value
    file_chooser.set_files(str(img_path))
    print("Uploaded night image via UI:", img_path.name)
    capture_step(page, state, "straighten-image-selected")


def wait_for_render(page: Page, timeout=30000, state: dict | None = None):
    """Wait for non-plot UI status to indicate render/compute completion."""
    try:
        page.wait_for_function(
            """
            () => {
                const txt = (document.getElementById('statusBadge')?.textContent || '').trim();
                return txt === 'Rendered' || txt.startsWith('Straightened') || txt.startsWith('Slit ');
            }
            """,
            timeout=timeout,
        )
    except Exception:
        pass
    capture_step(page, state, "render-status-settled")


def set_theme_via_ui(page: Page, state: dict, theme: str) -> None:
    """Set theme from the app UI selector, not via browser color-scheme hints."""
    target = "dark" if str(theme).lower() == "dark" else "light"
    _ensure_loaded(page, state)
    page.wait_for_selector("#themeSelect", timeout=30000)
    capture_step(page, state, f"theme-before-{target}")

    page.select_option("#themeSelect", value=target)
    page.dispatch_event("#themeSelect", "change")

    page.wait_for_function(
        """
        (targetTheme) => {
            const htmlTheme = document.documentElement.getAttribute('data-theme');
            const select = document.getElementById('themeSelect');
            return htmlTheme === targetTheme && !!select && select.value === targetTheme;
        }
        """,
        arg=target,
        timeout=30000,
    )

    # Theme selection triggers render via app event handlers; wait for settled state.
    wait_for_render(page, timeout=90000, state=state)
    capture_step(page, state, f"theme-after-{target}")


def dismiss_error_dialog(page: Page, state: dict | None = None):
    """Close the error dialog if it is open."""
    dialog = page.locator("#errorDialog[open]")
    if dialog.is_visible(timeout=500):
        try:
            msg = dialog.locator(
                "#errorDialogMessage, .error-message, p").first.inner_text(timeout=500)
        except Exception:
            msg = dialog.inner_text(timeout=500)
        print(f"[error dialog] {msg.strip()}")
        # Try pressing Escape or clicking a close/OK button inside
        close_btn = dialog.locator("button").first
        if close_btn.is_visible():
            close_btn.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        capture_step(page, state, "error-dialog-dismissed")


def click_tab(page: Page, label: str, state: dict | None = None):
    """Click a ribbon/nav tab by visible text."""
    capture_step(page, state, f"tab-before-{label}")
    tab = page.get_by_role("button", name=label, exact=False).first
    if tab.is_visible():
        tab.click()
    else:
        # fallback: any element with that text
        page.locator(f"text={label}").first.click()
    page.wait_for_timeout(700)
    capture_step(page, state, f"tab-after-{label}")


def is_spectra_active(page: Page) -> bool:
    """Best-effort check whether the Spectra toggle is currently active."""
    toggle = page.locator("#spectraToggle").first
    if toggle.count():
        try:
            return bool(toggle.evaluate(
                """
                (el) => {
                    if (el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio')) {
                        return !!el.checked;
                    }

                    const ariaPressed = el.getAttribute('aria-pressed');
                    const ariaChecked = el.getAttribute('aria-checked');
                    if (ariaPressed === 'true' || ariaChecked === 'true') return true;
                    if (ariaPressed === 'false' || ariaChecked === 'false') return false;

                    const cls = (el.className || '').toString().toLowerCase();
                    return /(active|selected|enabled|on|checked)/.test(cls);
                }
                """
            ))
        except Exception:
            pass

    return bool(page.evaluate(
        """
        () => {
            const byName = [
                ...Array.from(document.querySelectorAll('[role="switch"], [role="checkbox"], button, input, label')),
            ].filter((el) => {
                const txt = ((el.textContent || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                return txt.includes('spectra');
            });

            for (const el of byName) {
                const ariaPressed = el.getAttribute('aria-pressed');
                const ariaChecked = el.getAttribute('aria-checked');
                if (ariaPressed === 'true' || ariaChecked === 'true') return true;
                if (ariaPressed === 'false' || ariaChecked === 'false') continue;

                if (el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio')) {
                    if (el.checked) return true;
                    continue;
                }

                const cls = (el.className || '').toString().toLowerCase();
                if (/(active|selected|enabled|on)/.test(cls)) return true;
            }
            return false;
        }
        """
    ))


def click_spectra_toggle(page: Page, state: dict | None = None) -> bool:
    """Click the Spectra toggle control. Returns True if a control was clicked."""
    label = page.locator("label[for='spectraToggle']").first
    if label.count() and label.is_visible():
        label.click()
        page.wait_for_timeout(500)
        capture_step(page, state, "spectra-toggle-clicked")
        return True

    toggle = page.locator("#spectraToggle").first
    if toggle.count():
        # Hidden checkbox fallback: trigger click from JS.
        toggle.evaluate("(el) => el.click()")
        page.wait_for_timeout(500)
        capture_step(page, state, "spectra-toggle-clicked")
        return True

    for role in ("button", "switch", "checkbox"):
        candidate = page.get_by_role(role, name="Spectra", exact=False).first
        if candidate.count() and candidate.is_visible():
            candidate.click()
            page.wait_for_timeout(500)
            capture_step(page, state, "spectra-toggle-clicked")
            return True

    for selector in (
        "label:has-text('Spectra')",
        "button:has-text('Spectra')",
        "[aria-label*='spectra' i]",
        "[title*='spectra' i]",
    ):
        candidate = page.locator(selector).first
        if candidate.count() and candidate.is_visible():
            candidate.click()
            page.wait_for_timeout(500)
            capture_step(page, state, "spectra-toggle-clicked")
            return True

    return False


def annotate_ui(page: Page, labels: list[dict]) -> None:
    """Inject callout annotation overlays into the page.

    Each label dict has:
      selector  – CSS selector of the element to point at (used to get its bounding rect)
      text      – annotation label text
      side      – 'top' | 'bottom' | 'left' | 'right'  (which side of the element to annotate)
    """
    page.evaluate(
        """
        (labels) => {
            const CONTAINER_ID = '__playwright_annotations__';
            let container = document.getElementById(CONTAINER_ID);
            if (!container) {
                container = document.createElement('div');
                container.id = CONTAINER_ID;
                container.style.cssText =
                    'position:fixed;top:0;left:0;width:100%;height:100%;' +
                    'pointer-events:none;z-index:999999;';
                document.body.appendChild(container);
            }

            labels.forEach(({ selector, text, side, type }) => {
                const el = document.querySelector(selector);
                if (!el) return;

                const r = el.getBoundingClientRect();

                if (type === 'box') {
                    // Draw a coloured outline rectangle around the element
                    const box = document.createElement('div');
                    const pad = 3;
                    box.style.cssText =
                        'position:fixed;' +
                        'pointer-events:none;' +
                        'border:3px solid rgba(255,80,0,0.9);' +
                        'border-radius:4px;' +
                        'box-shadow:0 0 0 1px rgba(0,0,0,0.25);' +
                        'left:' + (r.left - pad) + 'px;' +
                        'top:' + (r.top - pad) + 'px;' +
                        'width:' + (r.width + pad * 2) + 'px;' +
                        'height:' + (r.height + pad * 2) + 'px;';
                    if (text) {
                        // Optional label in top-left corner of the box
                        const lbl = document.createElement('span');
                        lbl.style.cssText =
                            'position:absolute;bottom:100%;left:6px;' +
                            'background:rgba(255,80,0,0.92);color:#fff;' +
                            'font:bold 11px/1.4 system-ui,sans-serif;' +
                            'padding:1px 6px;border-radius:4px;' +
                            'white-space:nowrap;';
                        lbl.textContent = text;
                        box.appendChild(lbl);
                    }
                    container.appendChild(box);
                    return;
                }

                // Default: pill label + connector line
                const pill = document.createElement('div');
                pill.style.cssText =
                    'position:fixed;' +
                    'background:rgba(255,80,0,0.92);' +
                    'color:#fff;' +
                    'font:bold 13px/1.3 system-ui,sans-serif;' +
                    'padding:4px 10px;' +
                    'border-radius:4px;' +
                    'white-space:nowrap;' +
                    'box-shadow:0 2px 8px rgba(0,0,0,0.45);';
                pill.textContent = text;
                container.appendChild(pill);

                // Position pill then add arrow line
                const gap = 6;
                pill.style.left = (r.left + r.width / 2) + 'px';
                pill.style.transform = 'translateX(-50%)';

                if (side === 'bottom') {
                    pill.style.top = (r.bottom + gap) + 'px';
                } else {
                    // default: above
                    pill.style.top = (r.top - pill.offsetHeight - gap - 20) + 'px';
                }

                // Draw a line from pill to element edge
                const line = document.createElement('div');
                const pillRect = pill.getBoundingClientRect();
                const lineHeight = Math.abs(
                    side === 'bottom'
                        ? r.bottom + gap - r.bottom
                        : r.top - (pillRect.bottom || r.top - gap - 20)
                );

                line.style.cssText =
                    'position:fixed;' +
                    'width:2px;' +
                    'background:rgba(255,80,0,0.85);' +
                    'left:' + (r.left + r.width / 2) + 'px;' +
                    'transform:translateX(-50%);' +
                    (side === 'bottom'
                        ? 'top:' + r.bottom + 'px;height:' + gap + 'px;'
                        : 'top:' + (r.top - gap - 4) + 'px;height:' + (gap + 4) + 'px;');
                container.appendChild(line);
            });
        }
        """,
        labels,
    )


def remove_annotations(page: Page) -> None:
    """Remove all injected annotation overlays."""
    page.evaluate(
        """
        () => {
            const el = document.getElementById('__playwright_annotations__');
            if (el) el.remove();
        }
        """
    )


# ── Setup helpers ────────────────────────────────────────────────────────────

def _ensure_loaded(page: Page, state: dict) -> None:
    """Navigate to BASE and wait for initial load (once per browser context)."""
    if state.get("loaded"):
        return
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(2000)
    capture_step(page, state, "ui-launched")
    state["loaded"] = True


def _ensure_toml(page: Page, state: dict) -> None:
    """Load the example TOML via the UI (once per browser context)."""
    if state.get("toml_loaded"):
        return
    _ensure_loaded(page, state)
    load_instrument_toml(page, state)
    # Wait for the render auto-triggered by the TOML load to finish.
    try:
        page.wait_for_function(
            "() => document.getElementById('statusBadge')?.textContent?.trim() === 'Rendered'",
            timeout=90000,
        )
    except Exception:
        page.wait_for_timeout(10000)
    capture_step(page, state, "toml-loaded-rendered")
    state["toml_loaded"] = True


def _ensure_on_tab(page: Page, state: dict, tab: str) -> None:
    """Switch to `tab` if not already there."""
    if state.get("current_tab") == tab:
        return
    dismiss_error_dialog(page, state)
    click_tab(page, tab, state)
    state["current_tab"] = tab


def _ensure_rendered(page: Page, state: dict) -> None:
    """Perform a full render on the Layout tab (once per browser context)."""
    if state.get("rendered"):
        return
    _ensure_toml(page, state)
    _ensure_on_tab(page, state, "Layout")
    # Wait until the status badge confirms render is complete.
    try:
        page.wait_for_function(
            "() => document.getElementById('statusBadge')?.textContent?.trim() === 'Rendered'",
            timeout=90000,
        )
    except Exception:
        wait_for_render(page, state=state)
    dismiss_error_dialog(page, state)
    capture_step(page, state, "layout-rendered")
    state["rendered"] = True


def _ensure_mosaic_computed(page: Page, state: dict) -> None:
    """Switch to Mosaic Map and wait for the auto-compute to finish (once per browser context)."""
    if state.get("mosaic_computed"):
        return
    _ensure_rendered(page, state)
    _ensure_on_tab(page, state, "Mosaic Map")
    # The UI triggers fetchAndPopulateMosaicMap automatically on tab switch.
    # Poll for table rows (up to 2 min), dismissing any error dialogs that appear.
    deadline = 120  # seconds
    interval = 5
    elapsed = 0
    while elapsed < deadline:
        dismiss_error_dialog(page, state)
        try:
            page.wait_for_selector(
                "#slitOrderTable tbody tr", timeout=interval * 1000)
            break  # table populated — done
        except Exception:
            elapsed += interval
    dismiss_error_dialog(page, state)
    capture_step(page, state, "mosaic-computed")
    state["mosaic_computed"] = True


def _ensure_straighten_ready(page: Page, state: dict) -> None:
    """Prepare Straighten deterministically before capture — once per context."""
    if state.get("straighten_ready"):
        return

    # Ensure instrument TOML is loaded before entering Straighten.
    _ensure_toml(page, state)

    # Ensure the main render path is complete so straighten windows can initialize.
    _ensure_rendered(page, state)

    _ensure_on_tab(page, state, "Straighten")
    page.wait_for_selector("#straightenPanel:not(.hidden)", timeout=30000)
    capture_step(page, state, "straighten-tab-visible")

    # Upload calibration image immediately after entering Straighten so the
    # mapper is built from the uploaded image transform, matching manual usage.
    dismiss_error_dialog(page, state)
    upload_night_image(page, state)

    # Rebuild straighten state from the latest layout/uploaded transform.
    try:
        refreshed = page_get(
            page, "/api/straighten/windows?refresh_from_layout=true")
        if isinstance(refreshed, dict) and refreshed.get("_error"):
            print(
                f"Warning: straighten post-upload refresh returned {refreshed.get('_error')}")
    except Exception as exc:
        print(f"Warning: straighten post-upload refresh request failed: {exc}")

    # Wait for upload processing to occur and settle before selecting a window.
    deadline = 90
    interval = 1
    elapsed = 0
    saw_processing = False
    saw_loading = False
    while elapsed < deadline:
        dismiss_error_dialog(page, state)
        snapshot = page.evaluate(
            """
            () => {
                const badge = (document.getElementById('statusBadge')?.textContent || '').trim().toLowerCase();
                const loadingEl = document.getElementById('straightenWindowsLoading');
                const loadingVisible = !!loadingEl && !loadingEl.classList.contains('hidden');
                const buttons = document.querySelectorAll('#straightenWindowsButtons .straighten-window-btn').length;
                return { badge, loadingVisible, buttons };
            }
            """
        )

        badge = snapshot.get("badge", "")
        if "processing new image" in badge:
            saw_processing = True
        if snapshot.get("loadingVisible"):
            saw_loading = True

        # Preferred explicit completion status from frontend upload flow.
        if "image loaded successfully" in badge:
            break

        # Fallback completion: upload was observed (processing/loading), then
        # loading ended and window buttons are present.
        if (saw_processing or saw_loading) and (not snapshot.get("loadingVisible")) and snapshot.get("buttons", 0) > 0:
            break

        page.wait_for_timeout(interval * 1000)
        elapsed += interval
    else:
        print("Warning: upload completion signal not observed; continuing with latest straighten window state.")
    capture_step(page, state, "straighten-upload-settled")

    # Wait for post-upload window generation to complete.
    page.wait_for_selector(
        "#straightenWindowsButtons .straighten-window-btn",
        timeout=90000,
    )
    dismiss_error_dialog(page, state)
    capture_step(page, state, "straighten-windows-populated")

    def _wait_for_straighten_pass(window_name: str, pass_idx: int) -> None:
        # Capture baseline state right after click so we can detect real progress.
        baseline = page.evaluate(
            """
            () => {
                const badgeTxt = (document.getElementById('statusBadge')?.textContent || '').trim();
                return { badgeTxt };
            }
            """
        )
        baseline_badge = (baseline.get("badgeTxt") or "").strip()

        # Capture progress every second until straightening completes for the selected window.
        progress_deadline = 90
        progress_elapsed = 0
        progress_tick = 0
        saw_processing = False
        while progress_elapsed < progress_deadline:
            page.wait_for_timeout(1000)
            progress_elapsed += 1
            progress_tick += 1
            capture_step(
                page, state, f"straighten-pass-{pass_idx:02d}-progress-{progress_tick:03d}")

            progress = page.evaluate(
                """
                (windowName) => {
                    const badgeTxt = (document.getElementById('statusBadge')?.textContent || '').trim();
                    const normalized = badgeTxt.replace(/\\s+/g, ' ').trim();
                    const doneBadge = normalized.startsWith('Straightened')
                        && (!windowName || normalized === `Straightened ${windowName}`);
                    return { doneBadge, normalized };
                }
                """,
                arg=window_name,
            )

            # Require evidence of a fresh post-click transition to avoid accepting
            # stale "already straightened" status from a prior render.
            normalized = (progress.get("normalized") or "").strip()
            if normalized.startswith("Straightening"):
                saw_processing = True

            if normalized and normalized != baseline_badge:
                saw_processing = True

            if progress.get("doneBadge") and saw_processing:
                break
        else:
            print(
                f"Warning: straightening pass {pass_idx} did not report completion within 90 seconds.")

        # Final tolerant completion poll: avoid hanging on exact-string/title edge cases.
        settle_deadline = 20
        settle_elapsed = 0
        while settle_elapsed < settle_deadline:
            dismiss_error_dialog(page, state)
            final_state = page.evaluate(
                """
                (windowName) => {
                    const badgeTxt = (document.getElementById('statusBadge')?.textContent || '').trim();
                    const normalizedBadge = badgeTxt.replace(/\\s+/g, ' ').trim();
                    const doneBadge = normalizedBadge.startsWith('Straightened')
                        && (!windowName || normalizedBadge === `Straightened ${windowName}`);

                    const loadingEl = document.getElementById('straightenWindowsLoading');
                    const loadingVisible = !!loadingEl && !loadingEl.classList.contains('hidden');
                    return { doneBadge, loadingVisible };
                }
                """,
                arg=window_name,
            )

            if final_state.get("doneBadge") and not final_state.get("loadingVisible"):
                break

            page.wait_for_timeout(250)
            settle_elapsed += 0.25
        else:
            print(
                f"Warning: tolerant completion poll timed out on straighten pass {pass_idx}; continuing.")

    # Straighten only the target Hb/Hβ window once to match manual usage.
    all_windows = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('#straightenWindowsButtons .straighten-window-btn'))
            .map((btn) => (btn.getAttribute('data-window') || btn.textContent || '').trim())
            .filter((name) => !!name)
        """
    )
    all_windows = [str(w) for w in all_windows]

    if not all_windows:
        raise RuntimeError("No straighten windows available after upload.")

    hb_aliases = ("Hβ", "Hb", "Hbeta")
    target_window = next(
        (name for name in hb_aliases if name in all_windows), all_windows[0])

    # Single target pass only: avoids cross-window async response races.
    target_btn = page.locator(
        f"#straightenWindowsButtons .straighten-window-btn[data-window='{target_window}']"
    ).first
    target_btn.wait_for(timeout=10000)
    target_btn.click()
    capture_step(page, state, f"straighten-window-{target_window}-selected")
    _wait_for_straighten_pass(target_window, 1)
    capture_step(page, state, f"straighten-window-{target_window}-complete")

    dismiss_error_dialog(page, state)
    capture_step(page, state, "straighten-plot-ready")
    state["straighten_ready"] = True


# ── Individual shot functions ────────────────────────────────────────────────

def shot_01_initial(page: Page, out: Path, state: dict) -> None:
    _ensure_loaded(page, state)
    save_screenshot(page, out, "01-initial.png", state)
    print("Saved 01-initial.png")


def shot_11_menu_annotated(page: Page, out: Path, state: dict) -> None:
    _ensure_loaded(page, state)
    page.get_by_role("button", name="Menu", exact=False).first.click()
    page.wait_for_timeout(500)
    annotate_ui(page, [
        {"selector": "#topbarActions, #topbarActionsHome, .topbar-actions.floating-menu",
         "text": "Menu box",
         "type": "box"},
    ])
    save_screenshot(page, out, "11-menu-open-annotated.png", state)
    remove_annotations(page)
    print("Saved 11-menu-open-annotated.png")
    # Close menu so subsequent steps start from a consistent state.
    page.get_by_role("button", name="Menu", exact=False).first.click()
    page.wait_for_timeout(300)


def shot_10_layout_overview(page: Page, out: Path, state: dict) -> None:
    _ensure_loaded(page, state)
    page.get_by_role("button", name="Menu", exact=False).first.click()
    page.wait_for_timeout(500)
    try:
        page.get_by_role("button", name="Collapse All",
                         exact=False).first.click()
        page.wait_for_timeout(800)
    except Exception:
        pass
    annotate_ui(page, [
        {"selector": "nav, [role='navigation'], .view-ribbon, #viewRibbon, header",
         "text": "View ribbon — switch between modes",
         "type": "box"},
        {"selector": ".status-bar",
         "text": "Status bar — memory, theme, ready state",
         "type": "box"},
        {"selector": ".sidebar, #sidebar, aside, [role='complementary'], .control-panel, #controlPanel",
         "text": "Control sidebar",
         "type": "box"},
    ])
    save_screenshot(page, out, "10-layout-overview.png", state)
    remove_annotations(page)
    print("Saved 10-layout-overview.png")


def shot_02a_spectra(page: Page, out: Path, state: dict) -> None:
    _ensure_toml(page, state)
    _ensure_on_tab(page, state, "Layout")
    spectra_was_active = is_spectra_active(page)
    if not spectra_was_active:
        if click_spectra_toggle(page, state):
            print("Spectra toggle enabled.")
        else:
            print("Warning: Spectra toggle not found; skipping spectra screenshot.")
            return
    else:
        print("Spectra toggle already active.")
    page.wait_for_timeout(30000)
    save_screenshot(page, out, "02a-layout-spectra.png", state)
    print("Saved 02a-layout-spectra.png")
    click_spectra_toggle(page, state)
    page.wait_for_timeout(30000)
    print("Spectra toggle disabled.")


def shot_05a_spectra_popout(page: Page, out: Path, state: dict) -> None:
    _ensure_rendered(page, state)
    _ensure_on_tab(page, state, "Layout")
    dismiss_error_dialog(page, state)
    capture_step(page, state, "spectra-popout-before-open")

    page.locator("#openSpectraChip").first.click()
    page.wait_for_selector("#spectraSection[aria-expanded='true']", timeout=90000)
    page.wait_for_selector("#spectraTable", timeout=90000)
    page.wait_for_timeout(500)
    capture_step(page, state, "spectra-popout-opened")

    save_screenshot(page, out, "05a-layout-spectra-popout.png", state)
    print("Saved 05a-layout-spectra-popout.png")

    page.locator("#closeSpectraWindowBtn").first.click()
    page.wait_for_function(
        """
        () => {
            const section = document.getElementById('spectraSection');
            return !!section && section.getAttribute('aria-expanded') === 'false';
        }
        """,
        timeout=10000,
    )
    page.wait_for_timeout(300)
    capture_step(page, state, "spectra-popout-closed")


def shot_05b_combined_spectra_plot(page: Page, out: Path, state: dict) -> None:
    _ensure_rendered(page, state)
    _ensure_on_tab(page, state, "Layout")
    dismiss_error_dialog(page, state)
    capture_step(page, state, "combined-spectra-before-open")

    page.locator("#openSpectraChip").first.click()
    page.wait_for_selector("#spectraSection[aria-expanded='true']", timeout=90000)
    page.wait_for_selector("#spectraTable", timeout=90000)
    page.wait_for_timeout(400)
    capture_step(page, state, "combined-spectra-spectra-popout-opened")

    plot_btn = page.locator("#openCombinedSpectraPlotBtn").first
    plot_btn.wait_for(state="visible", timeout=10000)
    plot_btn.scroll_into_view_if_needed()
    try:
        plot_btn.click(timeout=5000)
    except Exception:
        plot_btn.evaluate("(el) => el.click()")
    page.wait_for_function(
        """
        () => {
            const section = document.getElementById('spectraPlotSection');
            const errorDialog = document.getElementById('errorDialog');
            if (errorDialog && errorDialog.hasAttribute('open')) {
                return 'error';
            }
            if (!section) {
                return false;
            }
            return section.getAttribute('aria-expanded') === 'true' && !section.classList.contains('hidden');
        }
        """,
        timeout=90000,
    )
    dismiss_error_dialog(page, state)
    page.wait_for_selector("#combinedSpectraPlot.js-plotly-plot", timeout=90000)
    page.wait_for_timeout(800)
    capture_step(page, state, "combined-spectra-plot-opened")

    save_screenshot(page, out, "05b-layout-combined-spectra-plot.png", state)
    print("Saved 05b-layout-combined-spectra-plot.png")

    page.locator("#closeSpectraPlotWindowBtn").first.click()
    page.wait_for_function(
        """
        () => {
            const section = document.getElementById('spectraPlotSection');
            return !!section
                && section.classList.contains('hidden')
                && section.getAttribute('aria-expanded') === 'false';
        }
        """,
        timeout=10000,
    )
    page.locator("#closeSpectraWindowBtn").first.click()
    page.wait_for_function(
        """
        () => {
            const section = document.getElementById('spectraSection');
            return !!section && section.getAttribute('aria-expanded') === 'false';
        }
        """,
        timeout=10000,
    )
    page.wait_for_timeout(300)
    capture_step(page, state, "combined-spectra-closed")


def shot_02_layout_view(page: Page, out: Path, state: dict) -> None:
    _ensure_rendered(page, state)
    save_screenshot(page, out, "02-layout-view.png", state)
    print("Saved 02-layout-view.png")


def shot_03_slits(page: Page, out: Path, state: dict) -> None:
    _ensure_toml(page, state)
    _ensure_on_tab(page, state, "Layout")
    page.get_by_role("button", name="Slits", exact=False).first.click()
    wait_for_render(page, state=state)
    save_screenshot(page, out, "03-layout-slits.png", state)
    print("Saved 03-layout-slits.png")
    page.get_by_role("button", name="Close Window", exact=False).first.click()
    page.wait_for_timeout(500)


def shot_04_windows(page: Page, out: Path, state: dict) -> None:
    _ensure_toml(page, state)
    _ensure_on_tab(page, state, "Layout")
    page.get_by_role("button", name="Windows", exact=False).first.click()
    wait_for_render(page, state=state)
    save_screenshot(page, out, "04-layout-windows.png", state)
    print("Saved 04-layout-windows.png")
    page.get_by_role("button", name="Close Window", exact=False).first.click()
    page.wait_for_timeout(500)


def shot_05_features(page: Page, out: Path, state: dict) -> None:
    _ensure_toml(page, state)
    _ensure_on_tab(page, state, "Layout")
    page.get_by_role("button", name="Features", exact=False).first.click()
    wait_for_render(page, state=state)
    save_screenshot(page, out, "05-layout-features.png", state)
    print("Saved 05-layout-features.png")
    page.get_by_role("button", name="Close Window", exact=False).first.click()
    page.wait_for_timeout(500)


def shot_05c_spectra_eq(page: Page, out: Path, state: dict) -> None:
    _ensure_rendered(page, state)
    _ensure_on_tab(page, state, "Layout")
    dismiss_error_dialog(page, state)
    capture_step(page, state, "spectra-eq-before-open")

    # Open the Spectra popout
    page.locator("#openSpectraChip").first.click()
    page.wait_for_selector("#spectraSection[aria-expanded='true']", timeout=90000)
    page.wait_for_selector("#spectraTable", timeout=90000)
    page.wait_for_timeout(400)
    capture_step(page, state, "spectra-eq-spectra-popout-opened")

    # Click the EQ button on the first spectra row
    eq_btn = page.locator("#spectraTable tbody tr:first-child button[data-row-action='eq']").first
    eq_btn.wait_for(state="visible", timeout=10000)
    eq_btn.scroll_into_view_if_needed()
    try:
        eq_btn.click(timeout=5000)
    except Exception:
        eq_btn.evaluate("(el) => el.click()")
    page.wait_for_selector("#spectraEqSection[aria-expanded='true']", timeout=30000)
    page.wait_for_selector("#spectraEqPlot.js-plotly-plot", timeout=30000)
    page.wait_for_timeout(800)
    capture_step(page, state, "spectra-eq-editor-opened")

    # Import the example EQ preset via the Import EQ file chooser
    eq_json = Path(__file__).parent / "day_spectra_eq.json"
    if eq_json.exists():
        import_label = page.locator("#spectraEqImportLabel").first
        import_label.wait_for(state="visible", timeout=10000)
        with page.expect_file_chooser() as fc_info:
            import_label.click()
        fc_info.value.set_files(str(eq_json))
        # Wait for the chart to re-render with the imported points
        page.wait_for_timeout(1000)
        capture_step(page, state, "spectra-eq-imported")
    else:
        print(f"Warning: EQ preset not found at {eq_json}; skipping import.")

    save_screenshot(page, out, "05c-layout-spectra-eq.png", state)
    print("Saved 05c-layout-spectra-eq.png")

    # Close EQ editor
    page.locator("#closeSpectraEqBtn").first.click()
    page.wait_for_function(
        """
        () => {
            const section = document.getElementById('spectraEqSection');
            return !!section && section.getAttribute('aria-expanded') === 'false';
        }
        """,
        timeout=10000,
    )
    # Close Spectra popout
    page.locator("#closeSpectraWindowBtn").first.click()
    page.wait_for_function(
        """
        () => {
            const section = document.getElementById('spectraSection');
            return !!section && section.getAttribute('aria-expanded') === 'false';
        }
        """,
        timeout=10000,
    )
    page.wait_for_timeout(300)
    capture_step(page, state, "spectra-eq-closed")


def shot_06_mosaic(page: Page, out: Path, state: dict) -> None:
    _ensure_mosaic_computed(page, state)
    dismiss_error_dialog(page, state)
    try:
        table_row = page.locator("#slitOrderTable tbody tr").first
        table_row.wait_for(state="visible", timeout=5000)
        table_row.click()
        wait_for_render(page, state=state)
    except Exception:
        pass
    save_screenshot(page, out, "06-mosaic-map.png", state)
    print("Saved 06-mosaic-map.png")


def shot_07_straighten(page: Page, out: Path, state: dict) -> None:
    _ensure_straighten_ready(page, state)
    save_screenshot(page, out, "07-straighten.png", state)
    print("Saved 07-straighten.png")


def shot_08_3d(page: Page, out: Path, state: dict) -> None:
    _ensure_toml(page, state)
    _ensure_on_tab(page, state, "3D Layout")
    page.wait_for_timeout(2500)   # WebGL needs time
    save_screenshot(page, out, "08-3d-layout.png", state)
    print("Saved 08-3d-layout.png")


def shot_09_sidebar(page: Page, out: Path, state: dict) -> None:
    _ensure_toml(page, state)
    _ensure_on_tab(page, state, "Layout")
    wait_for_render(page, state=state)
    save_screenshot(page, out, "09-layout-sidebar.png", state, full_page=False)
    print("Saved 09-layout-sidebar.png")


# ── Shot registry (defines canonical capture order) ─────────────────────────

SHOTS: dict[str, Callable] = {
    "01-initial":                shot_01_initial,
    "11-menu-open-annotated":    shot_11_menu_annotated,
    "10-layout-overview":        shot_10_layout_overview,
    "02a-layout-spectra":        shot_02a_spectra,
    "02-layout-view":            shot_02_layout_view,
    "03-layout-slits":           shot_03_slits,
    "04-layout-windows":         shot_04_windows,
    "05-layout-features":        shot_05_features,
    "05a-layout-spectra-popout": shot_05a_spectra_popout,
    "05b-layout-combined-spectra-plot": shot_05b_combined_spectra_plot,
    "05c-layout-spectra-eq":     shot_05c_spectra_eq,
    "06-mosaic-map":             shot_06_mosaic,
    # "07-straighten":             shot_07_straighten,
    "08-3d-layout":              shot_08_3d,
    "09-layout-sidebar":         shot_09_sidebar,
}


def _wait_for_cdp_ready(cdp_url: str, timeout_s: float) -> bool:
    """Poll the Chrome DevTools endpoint until it is reachable."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urlopen(f"{cdp_url}/json/version", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _launch_system_chrome_direct(pw, chrome_path: str, headless: bool = False) -> dict | None:
    """Launch system Chrome directly and connect via CDP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    cdp_port = sock.getsockname()[1]
    sock.close()

    user_data_dir = tempfile.mkdtemp(prefix="mssdesigner-chrome-")
    cmd = [
        chrome_path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
    ]
    if headless:
        cmd.append("--headless=new")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cdp_url = f"http://127.0.0.1:{cdp_port}"
    if not _wait_for_cdp_ready(cdp_url, timeout_s=15.0):
        try:
            proc.terminate()
        except Exception:
            pass
        shutil.rmtree(user_data_dir, ignore_errors=True)
        return None

    browser = pw.chromium.connect_over_cdp(cdp_url, timeout=15000)
    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context(viewport={"width": W, "height": H})

    return {
        "engine": "chrome-direct",
        "mode": "cdp",
        "browser": browser,
        "context": context,
        "process": proc,
        "user_data_dir": user_data_dir,
    }


def cleanup_capture_browser(launcher: dict) -> None:
    """Close browser/session resources created by launch_capture_browser."""
    browser = launcher.get("browser")
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass

    proc = launcher.get("process")
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    user_data_dir = launcher.get("user_data_dir")
    if user_data_dir:
        shutil.rmtree(user_data_dir, ignore_errors=True)


def launch_capture_browser(pw, browser_preference: str, headless: bool = True):
    """Launch a browser for capture.

    In `auto` mode, use Playwright's internal Chromium.
    Use `--browser chrome` to try system Chrome instead.
    """
    pref = (browser_preference or "auto").strip().lower()

    if pref == "chrome":
        chrome_path = None
        for name in ("google-chrome", "google-chrome-stable", "chrome"):
            found = shutil.which(name)
            if found:
                chrome_path = found
                break
        if chrome_path:
            try:
                direct = _launch_system_chrome_direct(
                    pw, chrome_path, headless=False)
                if direct is not None:
                    print(
                        f"Using system Google Chrome directly: {chrome_path}")
                    return direct
                print(f"Using system Google Chrome: {chrome_path}")
                browser = pw.chromium.launch(
                    executable_path=chrome_path,
                    headless=headless,
                    timeout=15000,
                )
                return {"engine": "chrome", "mode": "launch", "browser": browser}
            except Exception as exc:
                print(
                    f"Warning: failed to launch system Google Chrome ({exc}); falling back to Chromium.")
        else:
            print("Warning: system Google Chrome not found in PATH; using Chromium.")

    if pref == "firefox":
        firefox_path = shutil.which("firefox")
        if firefox_path:
            browser = None
            try:
                browser = pw.firefox.launch(
                    executable_path=firefox_path,
                    headless=headless,
                    timeout=15000,
                )
                probe_ctx = browser.new_context(
                    viewport={"width": 640, "height": 480})
                probe_page = probe_ctx.new_page()
                probe_page.goto(
                    "about:blank", wait_until="load", timeout=10000)
                probe_ctx.close()
                print(f"Using system Firefox: {firefox_path}")
                return {"engine": "firefox", "mode": "launch", "browser": browser}
            except Exception as exc:
                print(
                    f"Warning: failed to launch system Firefox ({exc}); falling back to Chromium.")
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
        else:
            print("Warning: system Firefox not found in PATH; falling back to Chromium.")

    browser = pw.chromium.launch(headless=headless, timeout=15000)
    print("Using Playwright Chromium.")
    return {"engine": "chromium", "mode": "launch", "browser": browser}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Capture SpectroForge screenshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Available shots:\n  " + "\n  ".join(SHOTS),
    )
    parser.add_argument(
        "--shots", nargs="+", metavar="SHOT",
        choices=list(SHOTS), default=list(SHOTS),
        help="One or more shot names to capture (default: all).",
    )
    parser.add_argument(
        "--theme", choices=("light", "dark", "both"), default="both",
        help="Color theme to capture (default: both).",
    )
    parser.add_argument(
        "--no-preview", "--no-disp", dest="no_preview", action="store_true",
        help="Disable live screenshot preview window.",
    )
    parser.add_argument(
        "--no-step-captures", action="store_true",
        help="Disable step-by-step action screenshots.",
    )
    parser.add_argument(
        "--browser", choices=("auto", "chrome", "firefox", "chromium"), default="auto",
        help="Browser engine to use: auto uses internal Chromium (default), chrome tries system Chrome, firefox uses system Firefox.",
    )
    args = parser.parse_args()

    schemes = ("light", "dark") if args.theme == "both" else (args.theme,)
    preview = ScreenshotPreview(enabled=not args.no_preview)
    try:
        with sync_playwright() as pw:
            launcher = launch_capture_browser(pw, args.browser, headless=True)
            for scheme in schemes:
                print(
                    f"\n── Capturing {scheme} mode ──────────────────────────────")
                print(f'Example Directory: {EXAMPLES}')

                if launcher.get("mode") == "cdp":
                    ctx = launcher["context"]
                    if ctx.pages:
                        page = ctx.pages[0]
                    else:
                        page = ctx.new_page()
                    page.set_viewport_size({"width": W, "height": H})
                else:
                    browser = launcher["browser"]
                    ctx = browser.new_context(
                        viewport={"width": W, "height": H},
                    )
                    page = ctx.new_page()

                out = OUT / scheme
                out.mkdir(parents=True, exist_ok=True)
                step_out = out / "steps"
                step_out.mkdir(parents=True, exist_ok=True)
                state: dict = {
                    "preview": preview,
                    "step_captures": not args.no_step_captures,
                    "step_out": step_out,
                    "step_index": 0,
                }
                set_theme_via_ui(page, state, scheme)
                for name in args.shots:
                    SHOTS[name](page, out, state)
                if launcher.get("mode") != "cdp":
                    ctx.close()
                print(f"Done. Screenshots in: {out}")
            cleanup_capture_browser(launcher)
    finally:
        preview.close()


if __name__ == "__main__":
    main()
