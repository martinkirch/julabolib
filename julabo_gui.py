#!/usr/bin/env python3
"""Graphical control panel for Julabo Economy Series CF30/CF40/FL11006 cooling units

Uses GTK3 (PyGObject) with cairo for temperature charting."""

# Copyright 2026 Martin Kirchgessner
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from julabolib import JULABO


class TempChart(Gtk.DrawingArea):
    """Simple line chart for temperature over time using cairo."""

    def __init__(self, max_points=120):
        super().__init__()
        self.max_points = max_points
        self.series = {}
        self.connect("draw", self.on_draw)
        self.set_size_request(-1, 240)

    def add_series(self, name, color):
        self.series[name] = {"color": color, "values": []}

    def push(self, name, value):
        if name not in self.series:
            return
        self.series[name]["values"].append(value)
        maxlen = self.max_points
        for s in self.series.values():
            while len(s["values"]) > maxlen:
                s["values"].pop(0)
        self.queue_draw()

    def clear_all(self):
        for entry in self.series.values():
            entry["values"].clear()
        self.queue_draw()

    def on_draw(self, widget, cr):
        alloc = widget.get_allocation()
        w, h = alloc.width, alloc.height
        if w <= 1 or h <= 1:
            return

        m_top, m_bot, m_left, m_right = 28, 34, 54, 16
        px, py = m_left, m_top
        pw = w - m_left - m_right
        ph = h - m_top - m_bot

        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        if not self.series:
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.move_to(w / 2, h / 2)
            cr.show_text("No data")
            return

        all_vals = []
        for entry in self.series.values():
            all_vals.extend(entry["values"])
        if not all_vals:
            return

        y_min = min(all_vals)
        y_max = max(all_vals)
        y_range = y_max - y_min
        if y_range < 1:
            y_range = 1
            mid = (y_min + y_max) / 2
            y_min = mid - y_range / 2
            y_max = mid + y_range / 2
        pad = y_range * 0.12
        y_min -= pad
        y_range += 2 * pad

        first = next(iter(self.series.values()))
        n = len(first["values"])
        if n == 0:
            return

        steps = 4
        cr.set_line_width(1)
        for i in range(steps + 1):
            yy = py + (ph / steps) * i
            cr.set_source_rgba(0.85, 0.85, 0.85, 1)
            cr.move_to(px, yy)
            cr.line_to(px + pw, yy)
            cr.stroke()
            val = y_max - (y_range / steps) * i
            cr.set_source_rgb(0.35, 0.35, 0.35)
            cr.move_to(4, yy + 4)
            cr.show_text("%.1f" % val)

        if n >= 2:
            cr.set_source_rgb(0.35, 0.35, 0.35)
            cr.move_to(px + pw - 14, h - 6)
            cr.show_text("now")
            cr.move_to(px, h - 6)
            cr.show_text("old")

        for name, data in self.series.items():
            vals = data["values"]
            if len(vals) < 2:
                continue
            r, g, b = data["color"]
            cr.set_source_rgb(r, g, b)
            cr.set_line_width(2)
            cr.move_to(px + pw, py + ph * (1 - (vals[0] - y_min) / y_range))
            for idx in range(1, len(vals)):
                x = px + pw * (1 - idx / (len(vals) - 1))
                y = py + ph * (1 - (vals[idx] - y_min) / y_range)
                cr.line_to(x, y)
            cr.stroke()

        lx = px + 6
        for name, data in self.series.items():
            r, g, b = data["color"]
            cr.set_source_rgb(r, g, b)
            cr.rectangle(lx, 6, 14, 4)
            cr.fill()
            cr.move_to(lx + 18, 10)
            cr.show_text(name)
            lx += cr.text_extents(name).width + 36

        cr.set_source_rgb(0.25, 0.25, 0.25)
        cr.move_to(w - m_right - 4, 10)
        cr.show_text("Temp (C)")


class JulaboApp(Gtk.Application):

    def __init__(self):
        super().__init__(application_id="app.julabo.gui", flags=0)
        self.julabo = None
        self.connected = False
        self.timer_id = 0

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self, title="Julabo Controller")
        win.set_default_size(720, 580)
        win.connect("destroy", self.on_destroy)
        self.window = win
        self._build_ui(win)
        win.show_all()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self, win):
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        main.set_border_width(8)
        win.add(main)

        # Connection bar
        conn = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        conn.set_border_width(4)
        conn.pack_start(Gtk.Label(label="Port:", xalign=0), False, False, 0)
        self.port_entry = Gtk.Entry()
        self.port_entry.set_text("/dev/ttyUSB0")
        self.port_entry.set_width_chars(14)
        conn.pack_start(self.port_entry, False, False, 0)

        self.baud_rate = 4800  # Julabo devices always use 4800

        self.btn_connect = Gtk.Button(label="Connect")
        self.btn_connect.connect("clicked", self.on_connect)
        conn.pack_start(self.btn_connect, False, False, 0)

        self.btn_disconnect = Gtk.Button(label="Disconnect")
        self.btn_disconnect.connect("clicked", self.on_disconnect)
        self.btn_disconnect.set_sensitive(False)
        conn.pack_start(self.btn_disconnect, False, False, 0)

        self.conn_label = Gtk.Label(label="Not connected", xalign=0)
        conn.pack_start(self.conn_label, False, False, 0)
        conn.pack_start(Gtk.Box(), True, True, 0)
        main.pack_start(conn, False, False, 0)

        # Power bar
        pwr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pwr.set_border_width(4)
        pwr.pack_start(Gtk.Label(label="Power:", xalign=0), False, False, 0)
        self.btn_on = Gtk.Button(label="ON")
        self.btn_on.connect("clicked", self.on_power_on)
        self.btn_on.set_sensitive(False)
        pwr.pack_start(self.btn_on, False, False, 0)
        self.btn_off = Gtk.Button(label="OFF")
        self.btn_off.connect("clicked", self.on_power_off)
        self.btn_off.set_sensitive(False)
        pwr.pack_start(self.btn_off, False, False, 0)
        self.pwr_label = Gtk.Label(label="--", xalign=0)
        pwr.pack_start(self.pwr_label, False, False, 0)
        pwr.pack_start(Gtk.Box(), True, True, 0)
        main.pack_start(pwr, False, False, 0)

        # Temperature controls
        temp = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        temp.set_border_width(4)
        temp.pack_start(Gtk.Label(label="Setpoint:", xalign=0), False, False, 0)
        self.sp_adj = Gtk.Adjustment(value=10.0, lower=-20, upper=100, step_increment=0.5, page_increment=1, page_size=0)
        self.sp_spin = Gtk.SpinButton(adjustment=self.sp_adj, digits=2, climb_rate=0.1)
        temp.pack_start(self.sp_spin, False, False, 0)
        self.btn_set_temp = Gtk.Button(label="Set")
        self.btn_set_temp.connect("clicked", self.on_set_temp)
        self.btn_set_temp.set_sensitive(False)
        temp.pack_start(self.btn_set_temp, False, False, 0)

        temp.pack_start(Gtk.Label(label="| Current:", xalign=0), False, False, 0)
        self.temp_label = Gtk.Label(label="--.- C", xalign=0)
        self.temp_label.set_width_chars(8)
        temp.pack_start(self.temp_label, False, False, 0)

        temp.pack_start(Gtk.Label(label="| Target:", xalign=0), False, False, 0)
        self.sp_ack_label = Gtk.Label(label="--.- C", xalign=0)
        self.sp_ack_label.set_width_chars(8)
        temp.pack_start(self.sp_ack_label, False, False, 0)
        temp.pack_start(Gtk.Box(), True, True, 0)
        main.pack_start(temp, False, False, 0)

        # Info row
        info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        info.set_border_width(4)
        info.pack_start(Gtk.Label(label="Version:", xalign=0), False, False, 0)
        self.ver_label = Gtk.Label(label="--", xalign=0)
        self.ver_label.set_width_chars(12)
        info.pack_start(self.ver_label, False, False, 0)
        info.pack_start(Gtk.Label(label="Status:", xalign=0), False, False, 0)
        self.st_label = Gtk.Label(label="--", xalign=0)
        self.st_label.set_width_chars(28)
        info.pack_start(self.st_label, False, False, 0)
        info.pack_start(Gtk.Box(), True, True, 0)
        main.pack_start(info, False, False, 0)

        # Buttons
        btnrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_refresh = Gtk.Button(label="Refresh All")
        self.btn_refresh.connect("clicked", self.on_refresh_all)
        self.btn_refresh.set_sensitive(False)
        btnrow.pack_start(self.btn_refresh, False, False, 0)
        self.btn_refresh_st = Gtk.Button(label="Refresh Status")
        self.btn_refresh_st.connect("clicked", self.on_refresh_status)
        self.btn_refresh_st.set_sensitive(False)
        btnrow.pack_start(self.btn_refresh_st, False, False, 0)
        btnrow.pack_start(Gtk.Box(), True, True, 0)
        main.pack_start(btnrow, False, False, 0)

        # Paned: chart + log
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.set_position(300)
        paned.pack1(self._make_chart(), True, True)
        paned.pack2(self._make_log(), True, True)
        main.pack_start(paned, True, True, 0)

    def _make_chart(self):
        frame = Gtk.Frame(label=" Temperature Log")
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        frame.add(sc)

        self.chart = TempChart(max_points=60)
        self.chart.add_series("Bath", (0.2, 0.4, 0.9))
        self.chart.add_series("Target", (0.8, 0.2, 0.2))
        sc.add(self.chart)
        return frame

    def _make_log(self):
        frame = Gtk.Frame(label=" Log")
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_left_margin(4)
        self.log_view.set_right_margin(4)
        self.log_buf = self.log_view.get_buffer()
        self.log_buf.create_tag("red", foreground="#c00")
        self.log_buf.create_tag("green", foreground="#070")
        self.log_buf.create_tag("dim", foreground="#888")
        self.log_buf.create_tag("bold", weight=700)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sc.add(self.log_view)
        frame.add(sc)
        return frame

    def _log(self, msg, tag="dim"):
        ts = time.strftime("%H:%M:%S")
        start = self.log_buf.get_end_iter()
        self.log_buf.insert(start, "[%s] %s\n" % (ts, msg))
        end = self.log_buf.get_end_iter()
        t = self.log_buf.get_tag_table().lookup(tag)
        if t:
            self.log_buf.apply_tag(t, start, end)
        mark = self.log_buf.get_insert()
        if mark:
            self.log_view.scroll_to_mark(mark, 0, False, 0, 0)

    def _set_ui_state(self, connected):
        self.connected = connected
        for w in (self.btn_on, self.btn_off, self.btn_set_temp,
                    self.btn_refresh, self.btn_refresh_st, self.port_entry):
            w.set_sensitive(connected)
        self.btn_connect.set_sensitive(not connected)
        self.btn_disconnect.set_sensitive(connected)
        self.sp_spin.set_sensitive(connected)
        self.conn_label.set_text("Connected" if connected else "Not connected")

    def _start_timer(self):
        self._stop_timer()
        self._chart_push_time = 0
        self.timer_id = GLib.timeout_add_seconds(2, self._poll_timer)

    def _stop_timer(self):
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = 0

    def _poll_timer(self):
        if not self.connected or not self.julabo:
            return False
        try:
            t = self.julabo.get_temperature()
            self.temp_label.set_text("%.1f C" % t)
            sp = self.julabo.get_work_temperature()
            self.sp_ack_label.set_text("%.2f C" % sp)
            self.sp_adj.set_value(sp)
            st = self.julabo.get_status()
            self.st_label.set_text(st.strip())
            now = time.time()
            if self._chart_push_time == 0 or now - self._chart_push_time >= 60:
                self.chart.push("Bath", t)
                self.chart.push("Target", sp)
                self._chart_push_time = now
        except Exception as e:
            self._log(str(e), "red")
        return True

    # -- Callbacks ---------------------------------------------------------

    def on_refresh_all(self, *_):
        if not self.connected or not self.julabo:
            return
        try:
            ver = self.julabo.get_version()
            self.ver_label.set_text(ver.strip())
            t = self.julabo.get_temperature()
            self.temp_label.set_text("%.1f C" % t)
            sp = self.julabo.get_work_temperature()
            self.sp_ack_label.set_text("%.2f C" % sp)
            self.sp_adj.set_value(sp)
            st = self.julabo.get_status()
            self.st_label.set_text(st.strip())
            pwr = self.julabo.get_power()
            self.pwr_label.set_text(pwr.strip())
            self._log("Refresh OK (t=%.1f sp=%.2f)" % (t, sp))
        except Exception as e:
            self._log("Refresh failed: " + str(e), "red")

    def on_refresh_status(self, *_):
        if not self.connected or not self.julabo:
            return
        try:
            st = self.julabo.get_status()
            self.st_label.set_text(st.strip())
            self._log(st.strip())
        except Exception as e:
            self._log("Status failed: " + str(e), "red")

    def on_connect(self, *_):
        port = self.port_entry.get_text()
        try:
            self.julabo = JULABO(port, self.baud_rate)
            self._set_ui_state(True)
            self.chart.clear_all()
            self._log("Connected to %s" % port, "green")
            self.on_refresh_all(None)
            self._start_timer()
        except Exception as e:
            self.julabo = None
            self._log("Connection failed: " + str(e), "red")

    def on_disconnect(self, *_):
        self._stop_timer()
        if self.julabo:
            try:
                self.julabo.close()
            except Exception:
                pass
            self.julabo = None
        self._set_ui_state(False)
        self.temp_label.set_text("--.- C")
        self.sp_ack_label.set_text("--.- C")
        self.st_label.set_text("--")
        self.ver_label.set_text("--")
        self.pwr_label.set_text("--")
        self._log("Disconnected", "dim")

    def on_power_on(self, *_):
        if not self.connected or not self.julabo:
            return
        try:
            self.julabo.set_power_on()
            self.pwr_label.set_text("ON")
            self._log("Power ON", "green")
        except Exception as e:
            self._log("Power on failed: " + str(e), "red")

    def on_power_off(self, *_):
        if not self.connected or not self.julabo:
            return
        try:
            self.julabo.set_power_off()
            self.pwr_label.set_text("OFF")
            self._log("Power OFF", "green")
        except Exception as e:
            self._log("Power off failed: " + str(e), "red")

    def on_set_temp(self, *_):
        if not self.connected or not self.julabo:
            return
        val = self.sp_adj.get_value()
        try:
            self.julabo.set_work_temperature(val)
            self._log("Setpoint set to %.2f C" % val, "green")
        except Exception as e:
            self._log("Set temp failed: " + str(e), "red")

    def on_destroy(self, *_):
        self.on_disconnect(None)


def main():
    app = JulaboApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
