import os
import sys
from bpy.app.handlers import persistent

# Blender does not always include the current user's Python site-packages path.
# Add it so optional packages such as psutil can be imported from Blender.
try:
    _user_site_packages = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "Python",
        f"Python{sys.version_info.major}{sys.version_info.minor}",
        "site-packages",
    )
    if os.path.isdir(_user_site_packages) and _user_site_packages not in sys.path:
        sys.path.insert(0, _user_site_packages)
except Exception as _path_exc:
    print(f"[Render Anywhere] Could not add user Python packages path: {_path_exc}")

import bpy
import time
import json
import re
import threading
import urllib.request

from bpy.props import (
    BoolProperty,
    StringProperty,
    FloatProperty,
    IntProperty,
)

from bpy.types import (
    Operator,
    Panel,
    PropertyGroup,
)


# ============================================================
# GLOBAL RENDER SESSION
# ============================================================


bl_info = {
    "name": "Render Anywhere",
    "author": "Your Name",
    "version": (0, 4, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Render Anywhere",
    "description": "Monitor Blender renders from an external application",
    "category": "System",
}


render_session = {
    "active": False,
    "frame_start": 0,
    "frame_end": 0,
    "current_frame": 0,
    "session_start": None,
    "frame_start_time": None,
    "completed_frames": 0,
    "total_frame_time": 0.0,
    "current_frame_time": 0.0,
    "average_frame_time": 0.0,
    "eta": 0.0,
    "memory": "?",
    "last_stats_send": 0.0,
}


# ============================================================
# PROPERTIES
# ============================================================


class RenderAnywhereProperties(PropertyGroup):

    current_samples: IntProperty(
        name="Current Samples",
        default=0,
        min=0,
    )

    monitoring_enabled: BoolProperty(
        name="Enable Monitoring",
        description="Enable Render Anywhere monitoring",
        default=False,
    )

    device_name: StringProperty(
        name="Device Name",
        description="Name used to identify this Blender installation",
        default="My Render PC",
    )

    server_address: StringProperty(
        name="Server Address",
        description="Render Anywhere server address",
        default="127.0.0.1",
    )

    server_port: IntProperty(
        name="Server Port",
        description="Render Anywhere server port",
        default=8765,
        min=1,
        max=65535,
    )

    connection_status: StringProperty(
        name="Connection Status",
        default="Disconnected",
    )

    render_status: StringProperty(
        name="Render Status",
        default="Idle",
    )

    current_frame: StringProperty(
        name="Current Frame",
        default="0",
    )

    total_frames: StringProperty(
        name="Total Frames",
        default="0",
    )

    progress: FloatProperty(
        name="Progress",
        default=0.0,
        min=0.0,
        max=100.0,
    )

    current_frame_time: FloatProperty(
        name="Current Frame Time",
        default=0.0,
    )

    average_frame_time: FloatProperty(
        name="Average Frame Time",
        default=0.0,
    )

    total_render_time: FloatProperty(
        name="Total Render Time",
        default=0.0,
    )

    estimated_time_remaining: FloatProperty(
        name="Estimated Time Remaining",
        default=0.0,
    )

    target_samples: IntProperty(
        name="Target Samples",
        description="Target number of Cycles samples",
        default=0,
        min=0,
    )


# ============================================================
# TIME FORMATTING
# ============================================================


def format_time(seconds):

    if seconds is None or seconds < 0:
        return "—"

    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    if hours > 0:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"

    if minutes > 0:
        return f"{minutes}m {seconds:02d}s"

    return f"{seconds}s"


# ============================================================
# NETWORKING
# ============================================================


def get_system_metrics():
    """Best-effort hardware metrics; unsupported metrics remain None."""
    metrics = {
        "cpu_percent": None,
        "ram_percent": None,
        "ram_used": None,
        "ram_total": None,
        "gpu_name": None,
        "gpu_percent": None,
        "gpu_temperature": None,
        "vram_used": None,
        "vram_total": None,
        "vram_percent": None,
    }

    # CPU and RAM metrics require psutil to be available inside Blender's Python.
    try:
        import psutil
        metrics["cpu_percent"] = float(psutil.cpu_percent(interval=None))
        ram = psutil.virtual_memory()
        metrics["ram_percent"] = float(ram.percent)
        metrics["ram_used"] = round(ram.used / (1024 ** 3), 2)
        metrics["ram_total"] = round(ram.total / (1024 ** 3), 2)
    except Exception as exc:
        print(f"[Render Anywhere] CPU/RAM metrics unavailable: {exc}")

    # GPU usage/temperature are available here for NVIDIA cards with NVML.
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            count = pynvml.nvmlDeviceGetCount()
            if count:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                metrics["gpu_name"] = name
                metrics["gpu_percent"] = float(util.gpu)
                metrics["gpu_temperature"] = int(
                    pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                )
                metrics["vram_used"] = round(mem.used / (1024 ** 3), 2)
                metrics["vram_total"] = round(mem.total / (1024 ** 3), 2)
                metrics["vram_percent"] = round((mem.used / mem.total) * 100, 1) if mem.total else None
        finally:
            pynvml.nvmlShutdown()
    except Exception as exc:
        # Non-NVIDIA GPUs, or Blender Python without pynvml, are supported;
        # their GPU-specific fields remain unavailable rather than breaking rendering.
        pass

    return metrics


def send_data(scene):
    if not hasattr(scene, "render_anywhere"):
        return

    props = scene.render_anywhere
    if not props.monitoring_enabled:
        return

    secret = __import__("os").environ.get("RELAY_SECRET")
    if not secret:
        props.connection_status = "Missing RELAY_SECRET"
        return

    frame = scene.frame_current
    start_frame = scene.frame_start
    end_frame = scene.frame_end
    total_frames = max(1, end_frame - start_frame + 1)

    status_text = str(props.render_status).lower()
    if status_text in ("rendering", "complete", "completed"):
        status = "completed" if status_text in ("complete", "completed") else "rendering"
    elif status_text in ("cancelled", "canceled"):
        status = "cancelled"
    elif status_text == "error":
        status = "error"
    else:
        status = "idle"

    frame_progress = min(1.0, max(0.0, float(props.progress) / 100.0))
    elapsed = max(0.0, float(props.total_render_time))
    remaining = max(0.0, float(props.estimated_time_remaining))

    metrics = get_system_metrics()

    data = {
        "device_id": "my-render-pc",
        "device_name": props.device_name,
        "status": status,
        "frame": frame,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "total_frames": total_frames,
        "sample": int(props.current_samples),
        "samples": int(props.target_samples),
        "frame_progress": frame_progress,
        "animation_progress": min(
            1.0,
            max(
                0.0,
                (
                    max(0, int(render_session.get("completed_frames", 0)))
                    + frame_progress
                )
                / max(
                    1,
                    int(render_session.get("frame_end", end_frame))
                    - int(render_session.get("frame_start", start_frame))
                    + 1,
                ),
            ),
        ),
        "remaining": format_time(remaining),
        "elapsed": round(elapsed, 2),
        "memory": render_session.get("memory", "?"),
        "cpu_percent": metrics["cpu_percent"],
        "ram_percent": metrics["ram_percent"],
        "ram_used": metrics["ram_used"],
        "ram_total": metrics["ram_total"],
        "gpu_name": metrics["gpu_name"],
        "gpu_percent": metrics["gpu_percent"],
        "gpu_temperature": metrics["gpu_temperature"],
        "vram_used": metrics["vram_used"],
        "vram_total": metrics["vram_total"],
        "vram_percent": metrics["vram_percent"],
        "blender_version": bpy.app.version_string,
        "scene": scene.name,
        "engine": scene.render.engine,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "current_frame_time": round(float(props.current_frame_time), 2),
        "average_frame_time": round(float(props.average_frame_time), 2),
        "total_render_time": round(elapsed, 2),
        "eta": round(remaining, 2),
        "target_samples": int(props.target_samples),
    }

    url = "wss://cloud.t0257354.workers.dev/?role=pc&device_id=my-render-pc"
    payload = json.dumps(data)

    def worker():
        ws = None
        try:
            import websocket
            ws = websocket.create_connection(
                url,
                timeout=5,
                header=[f"Authorization: Bearer {secret}"],
            )
            ws.send(payload)
        except Exception as exc:
            print(f"[Render Anywhere] Relay send failed: {exc}")
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    props.connection_status = "Sending"
    threading.Thread(target=worker, daemon=True).start()


# ============================================================
# RENDER HANDLERS
# ============================================================

@persistent
def render_init(scene):

    if not hasattr(scene, "render_anywhere"):
        return

    props = scene.render_anywhere

    if not props.monitoring_enabled:
        return

    global render_session

    render_session["active"] = True

    render_session["frame_start"] = scene.frame_start
    render_session["frame_end"] = scene.frame_end
    render_session["current_frame"] = scene.frame_current

    render_session["session_start"] = time.time()
    render_session["frame_start_time"] = time.time()

    render_session["completed_frames"] = 0
    render_session["total_frame_time"] = 0.0
    render_session["current_frame_time"] = 0.0
    render_session["average_frame_time"] = 0.0
    render_session["eta"] = 0.0
    render_session["memory"] = "?"
    render_session["last_stats_send"] = 0.0
    props.current_samples = 0

    props.render_status = "Rendering"

    props.current_frame = str(scene.frame_current)

    props.total_frames = str(scene.frame_end - scene.frame_start + 1)

    # Cycles sample target
    if scene.render.engine == "CYCLES":
        props.target_samples = scene.cycles.samples
    else:
        props.target_samples = 0

    props.progress = 0.0

    props.current_frame_time = 0.0
    props.average_frame_time = 0.0
    props.total_render_time = 0.0
    props.estimated_time_remaining = 0.0

    send_data(scene)


@persistent
def render_pre(scene):

    if not hasattr(scene, "render_anywhere"):
        return

    props = scene.render_anywhere

    if not props.monitoring_enabled:
        return

    global render_session

    render_session["frame_start_time"] = time.time()
    render_session["current_frame"] = scene.frame_current

    props.render_status = "Rendering"
    props.current_frame = str(scene.frame_current)

    send_data(scene)


@persistent
def render_post(scene):

    if not hasattr(scene, "render_anywhere"):
        return

    props = scene.render_anywhere

    if not props.monitoring_enabled:
        return

    global render_session

    now = time.time()

    frame_time = now - render_session["frame_start_time"]

    render_session["current_frame_time"] = frame_time

    render_session["total_frame_time"] += frame_time
    render_session["completed_frames"] += 1

    if render_session["completed_frames"] > 0:

        render_session["average_frame_time"] = (
            render_session["total_frame_time"] / render_session["completed_frames"]
        )

    if render_session["session_start"]:

        props.total_render_time = now - render_session["session_start"]

    render_session["current_frame"] = scene.frame_current

    props.current_frame = str(scene.frame_current)

    props.current_frame_time = frame_time

    props.average_frame_time = render_session["average_frame_time"]

    total_frames = render_session["frame_end"] - render_session["frame_start"] + 1

    if total_frames > 0:

        progress = (render_session["completed_frames"] / total_frames) * 100.0

        props.progress = min(progress, 100.0)

        remaining_frames = total_frames - render_session["completed_frames"]

        props.estimated_time_remaining = (
            remaining_frames * render_session["average_frame_time"]
        )

    send_data(scene)


@persistent
def render_complete(scene):

    if not hasattr(scene, "render_anywhere"):
        return

    props = scene.render_anywhere

    if not props.monitoring_enabled:
        return

    global render_session

    now = time.time()

    props.render_status = "Complete"

    props.progress = 100.0

    if render_session["session_start"]:

        props.total_render_time = now - render_session["session_start"]

    props.estimated_time_remaining = 0.0

    render_session["active"] = False

    send_data(scene)


@persistent
def render_cancel(scene):

    if not hasattr(scene, "render_anywhere"):
        return

    props = scene.render_anywhere

    if not props.monitoring_enabled:
        return

    global render_session

    props.render_status = "Cancelled"

    render_session["active"] = False

    send_data(scene)


# ============================================================
# OPERATOR
# ============================================================


class RENDERANYWHERE_OT_test_connection(Operator):
    bl_idname = "renderanywhere.test_connection"
    bl_label = "Test Connection"

    def execute(self, context):
        props = context.scene.render_anywhere
        secret = __import__("os").environ.get("RELAY_SECRET")

        if not secret:
            props.connection_status = "Missing RELAY_SECRET"
            self.report({"ERROR"}, "Set RELAY_SECRET in the environment before launching Blender")
            return {"CANCELLED"}

        ws = None
        try:
            import websocket

            url = "wss://cloud.t0257354.workers.dev/?role=pc&device_id=my-render-pc"
            ws = websocket.create_connection(
                url,
                timeout=5,
                header=[f"Authorization: Bearer {secret}"],
            )

            data = {
                "device_id": "my-render-pc",
                "device_name": props.device_name,
                "status": "idle",
                "frame": context.scene.frame_current,
                "start_frame": context.scene.frame_start,
                "end_frame": context.scene.frame_end,
                "total_frames": context.scene.frame_end - context.scene.frame_start + 1,
                "sample": int(props.current_samples),
                "samples": int(props.target_samples),
                "frame_progress": 0.0,
                "animation_progress": 0.0,
                "remaining": "?",
                "elapsed": "0s",
                "blender_version": bpy.app.version_string,
                "scene": context.scene.name,
                "engine": context.scene.render.engine,
                "resolution_x": context.scene.render.resolution_x,
                "resolution_y": context.scene.render.resolution_y,
            }
            ws.send(json.dumps(data))
            props.connection_status = "Connected"
            self.report({"INFO"}, "Authenticated Cloudflare relay connection successful")
            return {"FINISHED"}

        except Exception as exc:
            props.connection_status = "Error"
            self.report({"ERROR"}, f"Relay connection failed: {exc}")
            return {"CANCELLED"}

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass



class RENDERANYWHERE_OT_toggle(Operator):

    bl_idname = "renderanywhere.toggle"
    bl_label = "Toggle Render Anywhere"

    def execute(self, context):

        props = context.scene.render_anywhere

        props.monitoring_enabled = not (props.monitoring_enabled)

        if props.monitoring_enabled:

            props.render_status = "Idle"

            self.report({"INFO"}, "Render Anywhere enabled")

        else:

            props.render_status = "Monitoring disabled"

            self.report({"INFO"}, "Render Anywhere disabled")

        return {"FINISHED"}


# ============================================================
# UI PANEL
# ============================================================


class RENDERANYWHERE_PT_main(Panel):

    bl_label = "Render Anywhere"
    bl_idname = "RENDERANYWHERE_PT_main"

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Render Anywhere"

    def draw(self, context):

        layout = self.layout
        props = context.scene.render_anywhere

        # STATUS

        box = layout.box()

        if not props.monitoring_enabled:

            box.label(text="○ Monitoring disabled", icon="PAUSE")

        elif props.render_status == "Rendering":

            box.label(text="● Rendering", icon="REC")

        elif props.render_status == "Complete":

            box.label(text="✓ Render Complete", icon="CHECKMARK")

        elif props.render_status == "Cancelled":

            box.label(text="■ Render Cancelled", icon="CANCEL")

        else:

            box.label(text="● Monitoring active", icon="RADIOBUT_ON")

        # CONNECTION

        box = layout.box()

        box.label(text="Connection", icon="NETWORK_DRIVE")

        box.prop(props, "server_address")

        box.prop(props, "server_port")

        box.label(text=f"Status: {props.connection_status}")

        # DEVICE

        layout.prop(props, "device_name")

        # TOGGLE

        if props.monitoring_enabled:

            layout.operator(
                "renderanywhere.toggle", text="Stop Monitoring", icon="PAUSE"
            )

        else:

            layout.operator(
                "renderanywhere.toggle", text="Start Monitoring", icon="PLAY"
            )

        # RENDER INFORMATION

        box = layout.box()

        box.label(text="Render Information", icon="RENDER_STILL")

        box.label(text=f"Status: {props.render_status}")

        box.label(text=(f"Frame: " f"{props.current_frame} / " f"{props.total_frames}"))

        if context.scene.render.engine == "CYCLES":
            box.label(text=f"Samples: {context.scene.cycles.samples}")
        else:
            box.label(text="Samples: N/A")

        # PROGRESS

        row = box.row()

        row.label(text=f"Progress: {props.progress:.1f}%")

        row = box.row()

        row.prop(props, "progress", text="")

        # TIMING

        box.separator()

        box.label(text=("Current frame: " + format_time(props.current_frame_time)))

        box.label(text=("Average frame: " + format_time(props.average_frame_time)))

        box.label(text=("ETA: " + format_time(props.estimated_time_remaining)))

        box.label(text=("Total: " + format_time(props.total_render_time)))

        # BLENDER INFORMATION

        box = layout.box()

        box.label(text="Blender Information", icon="INFO")

        box.label(text=f"Version: {bpy.app.version_string}")

        box.label(text=f"Scene: {context.scene.name}")

        box.label(text=f"Engine: {context.scene.render.engine}")

        box.label(
            text=(
                f"Resolution: "
                f"{context.scene.render.resolution_x} × "
                f"{context.scene.render.resolution_y}"
            )
        )

        layout.operator(
            "renderanywhere.test_connection",
            text="Test Connection",
            icon="NETWORK_DRIVE",
        )


# ============================================================
# REGISTRATION
# ============================================================

classes = (
    RenderAnywhereProperties,
    RENDERANYWHERE_OT_toggle,
    RENDERANYWHERE_OT_test_connection,
    RENDERANYWHERE_PT_main,
)


@persistent
def render_stats(stats):
    """Consume Blender 5.2 render-stat strings and publish live Cycles progress."""
    global render_session

    if not render_session["active"]:
        return

    try:
        text = str(stats)

        # Blender's callback supplies strings such as:
        # "Remaining: 01:25.32 | Mem: 514M | Sample 10/256"
        memory_match = re.search(r"Mem:\s*([0-9.]+\s*[KMG]?)", text)
        if memory_match:
            render_session["memory"] = memory_match.group(1).replace(" ", "")

        sample_match = re.search(r"Sample\s+(\d+)/(\d+)", text)
        if sample_match:
            current_sample = int(sample_match.group(1))
            total_samples = int(sample_match.group(2))

            scene = bpy.context.scene
            if not scene or not hasattr(scene, "render_anywhere"):
                return
            props = scene.render_anywhere
            if not props.monitoring_enabled:
                return

            props.current_samples = current_sample
            if total_samples > 0:
                props.target_samples = total_samples
                frame_fraction = min(1.0, max(0.0, current_sample / total_samples))
                total_frames = max(
                    1,
                    render_session["frame_end"] - render_session["frame_start"] + 1,
                )
                completed = max(0, int(render_session["completed_frames"]))
                animation_fraction = min(
                    1.0, max(0.0, (completed + frame_fraction) / total_frames)
                )
                # The main progress bar represents the current frame's samples.
                props.progress = frame_fraction * 100.0

            remaining_match = re.search(r"Remaining:\s*([0-9:.]+)", text)
            if remaining_match:
                parts = remaining_match.group(1).split(":")
                try:
                    if len(parts) == 3:
                        remaining_seconds = (
                            float(parts[0]) * 3600
                            + float(parts[1]) * 60
                            + float(parts[2])
                        )
                    elif len(parts) == 2:
                        remaining_seconds = float(parts[0]) * 60 + float(parts[1])
                    else:
                        remaining_seconds = float(parts[0])
                    props.estimated_time_remaining = max(0.0, remaining_seconds)
                    render_session["eta"] = props.estimated_time_remaining
                except (TypeError, ValueError):
                    pass

            if render_session.get("session_start"):
                props.total_render_time = max(0.0, time.time() - render_session["session_start"])

            # Avoid opening a new WebSocket for every sample callback.
            # Update the phone at most about once per second.
            now = time.time()
            if now - render_session.get("last_stats_send", 0.0) >= 1.0 or current_sample == total_samples:
                render_session["last_stats_send"] = now
                send_data(scene)

        # Keep useful diagnostics for non-sample phases without flooding the console.
        elif "Cancelled" in text:
            print("[Render Anywhere] Blender reports render cancellation.")
    except Exception as exc:
        # A stats callback should never interrupt Blender's render.
        print(f"[Render Anywhere] Could not process render stats: {exc}")


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            try:
                bpy.utils.register_class(cls)
            except ValueError as exc:
                print(f"[Render Anywhere] Could not register {cls.__name__}: {exc}")

    bpy.types.Scene.render_anywhere = bpy.props.PointerProperty(
        type=RenderAnywhereProperties
    )

    if render_stats not in bpy.app.handlers.render_stats:
        bpy.app.handlers.render_stats.append(render_stats)


    if render_init not in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.append(render_init)

    if render_pre not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(render_pre)

    if render_post not in bpy.app.handlers.render_post:
        bpy.app.handlers.render_post.append(render_post)

    if render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(render_complete)

    if render_cancel not in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.append(render_cancel)


def unregister():

    if render_stats in bpy.app.handlers.render_stats:
        bpy.app.handlers.render_stats.remove(render_stats)

    if render_init in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.remove(render_init)

    if render_pre in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(render_pre)

    if render_post in bpy.app.handlers.render_post:
        bpy.app.handlers.render_post.remove(render_post)

    if render_complete in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(render_complete)

    if render_cancel in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.remove(render_cancel)

    del bpy.types.Scene.render_anywhere

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
