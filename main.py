#!/usr/bin/python
import errno
import os
import platform
import socket
import signal
import subprocess
import sys
import threading
import urllib.request
from shutil import rmtree
from time import sleep
from urllib.request import urlopen

import keyring
import requests
from packaging import version

# PyGObject

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Handy", "1")
gi.require_version("Notify", "0.7")
try:
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import Gtk, AppIndicator3 as appindicator
except ValueError: # Fix for Solus and other Ayatana users
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import Gtk, AyatanaAppIndicator3 as appindicator
from gi.repository import GLib
from gi.repository import GObject, Handy
from gi.repository import GdkPixbuf
from gi.repository import Notify
from gi.repository import Gdk

GObject.type_ensure(Handy.ActionRow)

APP_NAME = "althea"
ANISETTE_SERVER_URL = "http://127.0.0.1:6969"
computer_cpu_platform = platform.machine()
installedcheck = os.path.exists("/usr/lib/althea/althea")


def resource_path(relative_path):
    # Pick the packaged path first so the same code works for both source and installed runs
    base_path = "/usr/lib/althea" if installedcheck else os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# Global variables
ipa_path_exists = False
savedcheck = False
InsAltStore = subprocess.Popen(
    ["test"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
)
login_or_file_chooser = "login"
apple_id = "lol"
password = "lol"
Warnmsg = "warn"
Failmsg = "fail"
icon_name = "changes-prevent-symbolic"
command_six = Gtk.CheckMenuItem(label="Launch at Login")
altheapath = os.path.join(
    os.environ.get("XDG_DATA_HOME") or f'{ os.environ["HOME"] }/.local/share',
    "althea",
)
AltServer = os.path.join(altheapath, "AltServer")
AnisetteServer = os.path.join(altheapath, "anisette-server")
AltStore = os.path.join(altheapath, "AltStore.ipa")
INSTALL_PATH = AltStore
AutoStart = resource_path("resources/AutoStart.sh")
indicator = None

# Check version
with open(resource_path("resources/version"), "r", encoding="utf-8") as f:
    LocalVersion = f.readline().strip()


def anisette_env():
    # Keep the anisette endpoint in one place so every spawned helper gets the same value
    env = os.environ.copy()
    env["ALTSERVER_ANISETTE_SERVER"] = ANISETTE_SERVER_URL
    return env


def anisette_server_ready():
    # A short local probe is enough here because anisette should only be bound on localhost
    try:
        with urlopen(ANISETTE_SERVER_URL, timeout=2) as response:
            return response.read(1) == b"{"
    except OSError:
        return False


def should_use_tray():
    # Update //fork change! Skip tray mode on Hyprland because the tray popup path is crashing the compositor
    # Env flags keep the old behavior reachable for debugging without editing the file again
    if os.environ.get("ALTHEA_DISABLE_TRAY") == "1":
        return False
    if os.environ.get("ALTHEA_ENABLE_TRAY") == "1":
        return True
    return "Hyprland" not in os.environ.get("XDG_CURRENT_DESKTOP", "")


def kill_process_by_path(path):
    # Match by full path so unrelated processes with the same short name stay untouched
    subprocess.run(["pkill", "-f", path], check=False)


def terminate_althea_services():
    kill_process_by_path(AltServer)
    kill_process_by_path(AnisetteServer)


def download_to_file(url, destination):
    # Stream downloads to disk so large IPA and APK files do not sit in memory all at once
    with requests.get(url, stream=True, timeout=(10, 180)) as response:
        response.raise_for_status()
        with open(destination, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)


def read_log_text():
    # The installer writes progress to a plain log file, so the UI can poll one source of truth
    log_path = os.path.join(altheapath, "log.txt")
    if not os.path.exists(log_path):
        return ""
    with open(log_path, "r", encoding="utf-8", errors="replace") as file:
        return file.read()


def tail_lines(text, count):
    # Dialogs only need the latest lines, not the whole log
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-count:])

# Functions
def connectioncheck():
    # A simple socket probe avoids blocking startup on HTTP redirects or CDN quirks
    probes = [("1.1.1.1", 53), ("8.8.8.8", 53)]
    for host, port in probes:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            continue
    return False


def app_commands():
    # Keep the primary actions in one list so tray and window mode stay in sync
    return [
        ("About althea", on_abtdlg),
        ("Install AltStore", altstoreinstall),
        ("Install an IPA file", altserverfile),
        ("Pair", lambda x: openwindow(PairWindow)),
        ("Restart AltServer", restart_altserver),
        ("Quit althea", lambda x: quitit()),
    ]

def menu():
    # Build the tray menu from the shared command list
    menu = Gtk.Menu()

    if notify():
        command_upd = Gtk.MenuItem(label="Download Update")
        command_upd.connect("activate", showurl)
        menu.append(command_upd)

        menu.append(Gtk.SeparatorMenuItem())

    for label, callback in app_commands():
        command = Gtk.MenuItem(label=label)
        command.connect("activate", callback)
        menu.append(command)
        if label == "Settings":
            menu.append(Gtk.SeparatorMenuItem())

    if installedcheck:
        global command_six
        # Read the desktop entry directly instead of shelling out to test
        if os.path.exists(os.path.expanduser("~/.config/autostart/althea.desktop")):
            command_six.set_active(True)
        command_six.connect("activate", launchatlogin1)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(command_six)

    menu.show_all()
    return menu

def on_abtdlg(self):
    about = Gtk.AboutDialog()
    width = 100
    height = 100
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
        resource_path("resources/3.png"), width, height
    )
    about.set_logo(pixbuf)
    about.set_program_name("althea")
    about.set_version("0.5.0")
    about.set_authors(
        [
            "vyvir",
            "AltServer-Linux",
            "made by NyaMisty",
            "Provision",
            "made by Dadoum",
        ]
    )  # , 'Provision made by', 'Dadoum'])
    about.set_artists(["nebula"])
    about.set_comments("A GUI for AltServer-Linux written in Python.")
    about.set_website("https://github.com/vyvir/althea")
    about.set_website_label("Github")
    about.set_copyright("GUI by vyvir")
    about.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
    about.run()
    about.destroy()

def paircheck():  # Check if the device is paired already
    # Ask idevicepair directly and read its output instead of parsing a shell pipeline
    pairchecking = subprocess.run(
        ["idevicepair", "validate"],
        check=False,
        capture_output=True,
        text=True,
    )  # use validate instead of pair, pair causes error -5 if already paired
    output = f"{pairchecking.stdout}\n{pairchecking.stderr}"
    return "SUCCESS" not in output

def altstoreinstall(_):
    if version.parse(ios_version()) < version.parse("15.0"):
        global Warnmsg
        Warnmsg = f"""\niOS {ios_version()} is not supported by AltStore.\nThe lowest supported version is iOS 15.0.\nYou can still continue, but errors may occur.\n"""
        ios_dialog = WarningDialog(parent=None)
        ios_dialog.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        ios_response = ios_dialog.run()
        if ios_response == Gtk.ResponseType.OK:
            ios_dialog.destroy()
            if paircheck():
                openwindow(PairWindow)
            else:
                win1()
        elif ios_response == Gtk.ResponseType.CANCEL:
            ios_dialog.destroy()
    else:
        if paircheck():
            openwindow(PairWindow)
        else:
            win1()


def altserverfile(_):
    if paircheck():
        global login_or_file_chooser
        login_or_file_chooser = "file_chooser"
        openwindow(PairWindow)
    else:
        win2 = FileChooserWindow()
        global ipa_path_exists
        if ipa_path_exists:
            global INSTALL_PATH
            INSTALL_PATH = win2.PATHFILE
            win1()
            ipa_path_exists = False

def notify():
    # Update checks should never block the app from opening
    if not connectioncheck():
        return False
    try:
        LatestVersion = (
            urllib.request.urlopen(
                "https://raw.githubusercontent.com/vyvir/althea/main/resources/version",
                timeout=5,
            )
            .readline()
            .rstrip()
            .decode()
        )
        if version.parse(LatestVersion) > version.parse(LocalVersion):
            Notify.init(APP_NAME)
            n = Notify.Notification.new(
                "An update is available!",
                "Click 'Download Update' in the tray menu.",
                resource_path("resources/3.png"),
            )
            n.set_timeout(Notify.EXPIRES_DEFAULT)
            # n.add_action("newupd", "Download", actionCallback)
            n.show()
            return True
    except Exception:
        return False
    return False

def showurl(_):
    Gtk.show_uri_on_window(
        None, "https://github.com/vyvir/althea/releases", Gdk.CURRENT_TIME
    )
    quitit()

def openwindow(window):
    w = window()
    w.show_all()

def quitit():
    # Stop helper daemons before the GTK loop is torn down
    terminate_althea_services()
    Gtk.main_quit()
    os.kill(os.getpid(), signal.SIGKILL)

def restart_altserver(_):
    # Restart the helper pair with the same clean env used during startup
    terminate_althea_services()
    subprocess.run(["idevicepair", "pair"], check=False)
    subprocess.Popen(
        [AltServer],
        env=anisette_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

def use_saved_credentials():
    silent_remove(f"{(altheapath)}/log.txt")
    dialog = Gtk.MessageDialog(
        # transient_for=self,
        flags=0,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.YES_NO,
        text="Do you want to login automatically?",
    )
    dialog.format_secondary_text("Your login and password have been saved earlier.")
    response = dialog.run()
    if response == Gtk.ResponseType.YES:
        global apple_id
        global password
        apple_id = keyring.get_password("althea", "apple_id")
        password = keyring.get_password("althea", "password")
        #print(apple_id, password)
        global savedcheck
        savedcheck = True
        Login().on_click_me_clicked1()
    else:
        apple_id = keyring.delete_password("althea", "apple_id")
        password = keyring.delete_password("althea", "password")
        win3 = Login()
        win3.show_all()
    dialog.destroy()

def win1():
    try:
        if keyring.get_password("althea", "apple_id"):
            use_saved_credentials()
        else:
            openwindow(Login)
    except keyring.errors.KeyringError:
        openwindow(Login)

def win2(_):
    try:
        if keyring.get_password("althea", "apple_id"):
            use_saved_credentials()
        else:
            openwindow(Login)
    except keyring.errors.KeyringError:
        openwindow(Login)

def actionCallback(notification, action, user_data=None):
    Gtk.show_uri_on_window(
        None, "https://github.com/vyvir/althea/releases", Gdk.CURRENT_TIME
    )
    quitit()

def launchatlogin1(widget):
    # The same handler is used by both menu and window toggles
    active_widget = widget if hasattr(widget, "get_active") else command_six
    if active_widget.get_active():
        subprocess.run([AutoStart], check=False)
        return True
    else:
        silent_remove(os.path.expanduser("~/.config/autostart/althea.desktop"))
        return False

def silent_remove(filename):
    try:
        os.remove(filename)
    except OSError as e:
        if e.errno != errno.ENOENT:  # errno.ENOENT = no such file or directory
            raise  # re-raise exception if a different error occurred

def altstore_download(value):
    # setting the base URL value
    baseUrl = "https://cdn.altstore.io/file/altstore/apps.json"

    # retrieving data from JSON Data
    json_data = requests.get(baseUrl, timeout=(10, 60))
    if json_data.status_code == 200:
        data = json_data.json()
        for app in data['apps']:
            if app['name'] == "AltStore":
                if value == "Check":
                    size = app['versions'][0]['size']
                    return size == os.path.getsize(f'{(altheapath)}/AltStore.ipa')
                if value == "Download":
                    latest = app['versions'][0]['downloadURL']
                    latest_filename = latest.split('/')[-1]
                    # Save to a temp name first so a partial download never replaces the working IPA
                    download_to_file(latest, f"{(altheapath)}/{(latest_filename)}")
                    os.rename(f"{(altheapath)}/{(latest_filename)}", f"{(altheapath)}/AltStore.ipa")
                    os.chmod(f"{(altheapath)}/AltStore.ipa", 0o755)
                break
        return True
    else:
        return False

def ios_version():
    # Read the device version from stdout so no temporary file is needed
    result = subprocess.run(
        ["ideviceinfo"],
        check=False,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("ProductVersion: "):
            detected_version = line.split(": ", 1)[1].strip()
            print(detected_version)
            return detected_version
    return "0"

# Classes
class SplashScreen(Handy.Window):
    def __init__(self):
        super().__init__(title="Loading")
        self.set_resizable(False)
        self.set_default_size(512, 288)
        self.present()
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_keep_above(True)

        self.mainBox = Gtk.Box(
            spacing=6,
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.START,
            valign=Gtk.Align.START,
        )
        self.add(self.mainBox)

        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            filename=os.path.join("resources/4.png"),
            width=512,
            height=288,
            preserve_aspect_ratio=False,
        )
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        image.show()
        self.mainBox.pack_start(image, False, True, 0)

        self.lbl1 = Gtk.Label(label="Starting althea...")
        self.mainBox.pack_start(self.lbl1, False, False, 6)
        self.loadalthea = Gtk.ProgressBar()
        self.mainBox.pack_start(self.loadalthea, True, True, 0)
        # Update //fork change! Startup work runs off the GTK thread and only feeds progress back through idle callbacks
        self.t = threading.Thread(target=self.startup_process, daemon=True)
        self.t.start()
        self.wait_for_t(self.t)

    def wait_for_t(self, t):
        if not self.t.is_alive():
            global indicator
            if indicator is not None:
                indicator.set_status(appindicator.IndicatorStatus.ACTIVE)
            self.t.join()
            self.destroy()
            # In window mode the splash hands off to the main control window instead of a tray icon
            if indicator is None:
                openwindow(MainWindow)
        else:
            GLib.timeout_add(200, self.wait_for_t, self.t)

    def set_status_text(self, text):
        # GTK widgets must be touched from the main loop
        GLib.idle_add(self.lbl1.set_text, text)

    def set_progress(self, fraction):
        # GTK widgets must be touched from the main loop
        GLib.idle_add(self.loadalthea.set_fraction, fraction)

    def download_bin(self, name, link):
        # Pick the matching binary once and feed the same download helper for every arch
        match computer_cpu_platform:
            case 'x86_64':
                url = f"{link}-x86_64"
            case 'aarch64':
                url = f"{link}-aarch64"
            case _:
                if computer_cpu_platform.find('v7') != -1 \
                    or computer_cpu_platform.find('ARM') != -1 \
                        or computer_cpu_platform.find('hf') != -1:
                            url = f"{link}-armv7"
                else:
                    self.set_status_text('Could not identify the CPU architecture, downloading the x86_64 version...')
                    url = f"{link}-x86_64"
        download_to_file(url, f"{(altheapath)}/{name}")
        os.chmod(f"{(altheapath)}/{name}", 0o755)

    
    def startup_process(self):
        # Update //fork change! Startup now uses direct subprocess calls and streamed downloads instead of shell-built commands
        self.set_status_text("Checking if anisette-server is already running...")
        self.set_progress(0.1)
        if not os.path.isfile(f"{(altheapath)}/anisette-server"):
            self.set_status_text("Downloading anisette-server...")
            self.download_bin("anisette-server", "https://github.com/vyvir/althea/releases/download/v0.5.0/anisette-server")
            self.set_progress(0.2)
            self.set_status_text("Downloading Apple Music APK...")
            download_to_file(
                "https://apps.mzstatic.com/content/android-apple-music-apk/applemusic.apk",
                f"{(altheapath)}/am.apk",
            )
            os.makedirs(f"{(altheapath)}/lib/x86_64", exist_ok=True)
            self.set_progress(0.3)
            self.set_status_text("Extracting necessary libraries...")
            subprocess.run(
                [
                    "unzip",
                    "-j",
                    f"{(altheapath)}/am.apk",
                    "lib/x86_64/libstoreservicescore.so",
                    "-d",
                    f"{(altheapath)}/lib/x86_64",
                ],
                check=False,
            )
            subprocess.run(
                [
                    "unzip",
                    "-j",
                    f"{(altheapath)}/am.apk",
                    "lib/x86_64/libCoreADI.so",
                    "-d",
                    f"{(altheapath)}/lib/x86_64",
                ],
                check=False,
            )
            silent_remove(f"{(altheapath)}/am.apk")
            self.set_progress(0.4)
        self.set_status_text("Starting anisette-server...")
        subprocess.Popen(
            [AnisetteServer, "-n", "127.0.0.1", "-p", "6969"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.set_progress(0.5)
        finished = False
        while not finished:
            # Wait until anisette is actually answering before AltServer is started
            if anisette_server_ready():
                finished = True
            else:
                sleep(1)
        if not os.path.isfile(f"{(altheapath)}/AltServer"):
            self.download_bin("AltServer", "https://github.com/NyaMisty/AltServer-Linux/releases/download/v0.0.5/AltServer")
            self.set_status_text("Downloading AltServer...")
            self.set_progress(0.6)
        self.set_progress(0.8)
        if not os.path.isfile(f"{(altheapath)}/AltStore.ipa"):
            self.set_status_text("Downloading AltStore...")
            altstore_download("Download")
        else:
            self.set_status_text("Checking latest AltStore version...")
            if not altstore_download("Check"):
                self.set_status_text("Downloading new version of AltStore...")
                altstore_download("Download")
        self.set_status_text("Starting AltServer...")
        self.set_progress(1.0)
        subprocess.Popen(
            [AltServer],
            env=anisette_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return 0


class MainWindow(Handy.Window):
    def __init__(self):
        super().__init__(title="althea")
        self.present()
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_resizable(False)
        self.set_border_width(16)
        self.set_default_size(420, 360)

        handle = Handy.WindowHandle()
        self.add(handle)

        outer = Gtk.Box(spacing=12, orientation=Gtk.Orientation.VERTICAL)
        handle.add(outer)

        header = Handy.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = "althea"
        outer.pack_start(header, False, True, 0)

        body = Gtk.Box(spacing=10, orientation=Gtk.Orientation.VERTICAL)
        body.set_margin_top(8)
        outer.pack_start(body, True, True, 0)

        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(
            resource_path("resources/3.png"), 72, 72
        )
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        body.pack_start(image, False, False, 0)

        title = Gtk.Label(label="althea controls")
        title.set_justify(Gtk.Justification.CENTER)
        body.pack_start(title, False, False, 0)

        # Update //fork change! This window replaces the tray workflow on Hyprland so popup menus stop taking down the compositor
        subtitle = Gtk.Label(
            label="Tray integration is disabled on Hyprland to avoid a repeated compositor crash."
        )
        subtitle.set_line_wrap(True)
        subtitle.set_max_width_chars(42)
        subtitle.set_justify(Gtk.Justification.CENTER)
        body.pack_start(subtitle, False, False, 0)

        for label, callback in app_commands():
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            body.pack_start(button, False, False, 0)

        if installedcheck:
            launch_at_login = Gtk.CheckButton(label="Launch at Login")
            launch_at_login.set_active(
                os.path.exists(os.path.expanduser("~/.config/autostart/althea.desktop"))
            )
            launch_at_login.connect("toggled", launchatlogin1)
            body.pack_start(launch_at_login, False, False, 0)

        self.connect("destroy", self.on_destroy)
        self.show_all()

    def on_destroy(self, widget):
        # Window mode has no tray fallback on Hyprland, so closing the main window should fully quit
        quitit()


class Login(Gtk.Window):
    def __init__(self):
        super().__init__(title="Login")
        self.present()
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_resizable(False)
        self.set_border_width(10)

        grid = Gtk.Grid()
        self.add(grid)

        label = Gtk.Label(label="Apple ID: ")
        label.set_justify(Gtk.Justification.LEFT)

        self.entry1 = Gtk.Entry()

        label1 = Gtk.Label(label="Password: ")
        label1.set_justify(Gtk.Justification.LEFT)

        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        global icon_name
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, icon_name)
        self.entry.connect("icon-press", self.on_icon_toggled)

        self.button = Gtk.Button.new_with_label("Login")
        self.button.connect("clicked", self.on_click_me_clicked)

        grid.add(label)
        grid.attach(self.entry1, 1, 0, 2, 1)
        grid.attach_next_to(label1, label, Gtk.PositionType.BOTTOM, 1, 2)
        grid.attach(self.entry, 1, 2, 1, 1)
        grid.attach_next_to(self.button, self.entry, Gtk.PositionType.RIGHT, 1, 1)

        silent_remove(f"{(altheapath)}/log.txt")
        self.install_monitor_id = None
        self.install_warn_seen = False
        self.install_two_factor_seen = False
        self.installing = False

    def on_click_me_clicked1(self):
        # Saved credentials follow the same worker path as a manual login
        self.realthread1 = threading.Thread(target=self.onclickmethread, daemon=True)
        self.realthread1.start()
        self.start_install_monitor()

    def on_click_me_clicked(self, button):
        silent_remove(f"{(altheapath)}/log.txt")
        try:
            if not keyring.get_password("althea", "apple_id"):
                self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.QUESTION,
                    buttons=Gtk.ButtonsType.YES_NO,
                    text="Do you want to save your login and password?",
                )
                dialog.format_secondary_text("This will allow you to login automatically.")
                response = dialog.run()
                if response == Gtk.ResponseType.YES:
                    apple_id = self.entry1.get_text().lower()
                    password = self.entry.get_text()
                    keyring.set_password("althea", "apple_id", apple_id)
                    keyring.set_password("althea", "password", password)
                dialog.destroy()
        except keyring.errors.KeyringError:
            pass
        self.entry.set_progress_pulse_step(0.2)
        # Call self.do_pulse every 100 ms
        self.timeout_id = GLib.timeout_add(100, self.do_pulse, None)
        self.entry.set_editable(False)
        self.entry1.set_editable(False)
        self.button.set_sensitive(False)
        self.realthread1 = threading.Thread(target=self.onclickmethread, daemon=True)
        self.realthread1.start()
        self.start_install_monitor()

    def start_install_monitor(self):
        # Update //fork change! Install state is polled by a GTK timer so the main loop stays responsive
        self.installing = True
        self.install_warn_seen = False
        self.install_two_factor_seen = False
        if self.install_monitor_id is None:
            self.install_monitor_id = GLib.timeout_add(300, self.install_process)

    def onclickmethread(self):
        # The worker only does device and process work, leaving dialogs to the main loop
        if version.parse(ios_version()) >= version.parse("15.0"):
            global savedcheck
            global apple_id
            global password
            if not savedcheck:
                apple_id = self.entry1.get_text().lower()
                password = self.entry.get_text()
            UDID = subprocess.check_output(["idevice_id", "-l"]).decode().strip()
            global InsAltStore
            print(INSTALL_PATH)
            silent_remove(f"{(altheapath)}/log.txt")
            if os.path.isdir(f'{ os.environ["HOME"] }/.adi'):
                rmtree(f'{ os.environ["HOME"] }/.adi')
            with open(f"{(altheapath)}/log.txt", "w", encoding="utf-8") as log_file:
                # Update //fork change! Install commands are passed as argv so Apple ID, password, and IPA path do not go through a shell
                InsAltStore = subprocess.Popen(
                    [AltServer, "-u", UDID, "-a", apple_id, "-p", password, INSTALL_PATH],
                    stdin=subprocess.PIPE,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=anisette_env(),
                    text=False,
                )
        else:
            global Failmsg
            Failmsg = "iOS 15.0 or later is required."
            GLib.idle_add(self.show_fail_and_close)

    def show_fail_and_close(self):
        # Keep failure dialogs on the GTK thread
        dialog2 = FailDialog(self)
        dialog2.run()
        dialog2.destroy()
        self.destroy()
        return False

    def install_process(self):
        global Failmsg
        global InsAltStore
        # The log file is the single source of truth for prompts and failure text
        log_text = read_log_text()
        if not self.realthread1.is_alive() and not log_text and InsAltStore.poll() is not None:
            self.installing = False
            self.install_monitor_id = None
            return False

        if "Could not" in log_text:
            InsAltStore.terminate()
            self.installing = False
            self.install_monitor_id = None
            Failmsg = tail_lines(log_text, 6)
            dialog2 = FailDialog(self)
            dialog2.run()
            dialog2.destroy()
            self.destroy()
            return False

        if "Are you sure you want to continue?" in log_text and not self.install_warn_seen:
            self.install_warn_seen = True
            global Warnmsg
            Warnmsg = tail_lines(log_text, 8)
            dialog1 = WarningDialog(self)
            response1 = dialog1.run()
            dialog1.destroy()
            if response1 == Gtk.ResponseType.OK:
                if InsAltStore.stdin is not None:
                    # Feed the warning prompt without blocking on communicate
                    InsAltStore.stdin.write(b"\n")
                    InsAltStore.stdin.flush()
            else:
                subprocess.run(["pkill", "-TERM", "-P", str(InsAltStore.pid)], check=False)
                InsAltStore.terminate()
                self.cancel()
                self.destroy()
                self.installing = False
                self.install_monitor_id = None
                return False

        if "Enter two factor code" in log_text and not self.install_two_factor_seen:
            self.install_two_factor_seen = True
            dialog = VerificationDialog(self)
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                vercode = f"{dialog.entry2.get_text()}\n".encode()
                if InsAltStore.stdin is not None:
                    # Feed the 2FA code the same way as the warning prompt
                    InsAltStore.stdin.write(vercode)
                    InsAltStore.stdin.flush()
            else:
                subprocess.run(["pkill", "-TERM", "-P", str(InsAltStore.pid)], check=False)
                InsAltStore.terminate()
                self.cancel()
                dialog.destroy()
                self.destroy()
                self.installing = False
                self.install_monitor_id = None
                return False
            dialog.destroy()

        if "Notify: Installation Succeeded" in log_text:
            self.installing = False
            self.install_monitor_id = None
            self.success()
            self.destroy()
            return False

        if not self.realthread1.is_alive() and InsAltStore.poll() not in (None, 0):
            self.installing = False
            self.install_monitor_id = None
            Failmsg = tail_lines(log_text, 10) or "AltServer exited before the install completed."
            dialog2 = FailDialog(self)
            dialog2.run()
            dialog2.destroy()
            self.destroy()
            return False

        return True

    def success(self):
        # Keep success feedback short because the heavy work already finished
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Success!",
        )
        dialog.format_secondary_text("Operation completed")
        dialog.run()
        dialog.destroy()

    def cancel(self):
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Cancelled",
        )
        dialog.format_secondary_text("Operation cancelled by user")
        dialog.run()
        dialog.destroy()

    def do_pulse(self, user_data):
        self.entry.progress_pulse()
        return True

    def on_icon_toggled(self, widget, icon, event):
        global icon_name
        if icon_name == "changes-prevent-symbolic":
            icon_name = "changes-allow-symbolic"
            self.entry.set_visibility(True)
        elif icon_name == "changes-allow-symbolic":
            icon_name = "changes-prevent-symbolic"
            self.entry.set_visibility(False)
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, icon_name)

    #
    #def on_editable_toggled(self, widget):
    #    print("lol")


class PairWindow(Handy.Window):
    def __init__(self):
        super().__init__(title="Pair your device")
        self.present()
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_resizable(False)
        self.set_border_width(20)

        self.handle = Handy.WindowHandle()
        self.add(self.handle)

        self.hbox = Gtk.Box(spacing=5, orientation=Gtk.Orientation.VERTICAL)
        self.handle.add(self.hbox)

        self.hb = Handy.HeaderBar()
        self.hb.set_show_close_button(True)
        self.hb.props.title = "Pair your device"
        self.hbox.pack_start(self.hb, False, True, 0)

        pixbuf = Gtk.IconTheme.get_default().load_icon(
            "phone-apple-iphone-symbolic", 48, 0
        )
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        image.show()
        image.set_margin_top(5)
        self.hbox.pack_start(image, True, True, 0)

        lbl1 = Gtk.Label(
            label="Please make sure your device is connected to the computer.\nPress 'Pair' to pair your device."
        )
        lbl1.set_property("margin_left", 15)
        lbl1.set_property("margin_right", 15)
        lbl1.set_margin_top(5)
        lbl1.set_justify(Gtk.Justification.CENTER)
        self.hbox.pack_start(lbl1, False, False, 0)

        button = Gtk.Button(label="Pair")
        button.connect("clicked", self.on_info_clicked)
        button.set_property("margin_left", 150)
        button.set_property("margin_right", 150)
        self.hbox.pack_start(button, False, False, 10)

    def on_info_clicked(self, widget):
        # The first call nudges the device trust dialog if it is still pending
        try:
            subprocess.run(["idevicepair", "pair"], check=True)
        except subprocess.CalledProcessError as e:
            print(e.output)
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Accept the trust dialog on the screen of your device,\nthen press 'OK'.",
            )

            dialog.run()
        try:
            # The second call confirms pairing and then moves back into the install flow
            subprocess.run(
                ["idevicepair", "pair"], check=True, capture_output=True
            )
            self.destroy()
            global login_or_file_chooser
            global INSTALL_PATH
            if login_or_file_chooser == "file_chooser":
                win2 = FileChooserWindow()
            else:
                INSTALL_PATH = f"{(altheapath)}/AltStore.ipa"
                win1()
            global ipa_path_exists
            if ipa_path_exists:
                INSTALL_PATH = win2.PATHFILE
                win1()
                ipa_path_exists = False
            login_or_file_chooser = "login"
        except subprocess.CalledProcessError as e:
            errormsg = e.output.decode("utf-8")
            dialog1 = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=(errormsg),
            )
            dialog1.run()
            dialog1.destroy()
        try:
            dialog.destroy()
        except NameError:
            pass


class FileChooserWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="File chooser")
        box = Gtk.Box()
        self.add(box)

        dialog = Gtk.FileChooserDialog(
            title="Please choose a file", parent=self, action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.OK,
        )

        self.add_filters(dialog)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.PATHFILE = dialog.get_filename()
            global ipa_path_exists
            ipa_path_exists = True
        elif response == Gtk.ResponseType.CANCEL:
            self.destroy()

        dialog.destroy()

    def add_filters(self, dialog):
        filter_ipa = Gtk.FileFilter()
        filter_ipa.set_name("IPA files")
        filter_ipa.add_pattern("*.ipa")
        dialog.add_filter(filter_ipa)

        filter_any = Gtk.FileFilter()
        filter_any.set_name("Any files")
        filter_any.add_pattern("*")
        dialog.add_filter(filter_any)


class VerificationDialog(Gtk.Dialog):
    def __init__(self, parent):
        if not savedcheck:
            super().__init__(title="Verification code", transient_for=parent, flags=0)
        else:
            super().__init__(title="Verification code", flags=0)
        self.present()
        self.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,
            Gtk.ResponseType.OK,
        )
        self.set_resizable(True)
        self.set_border_width(10)

        labelhelp = Gtk.Label(
            label="Enter the verification \ncode on your device: "
        )
        labelhelp.set_justify(Gtk.Justification.CENTER)

        self.entry2 = Gtk.Entry()

        box = self.get_content_area()
        box.add(labelhelp)
        box.add(self.entry2)
        self.show_all()


class WarningDialog(Gtk.Dialog):
    def __init__(self, parent):
        global Warnmsg
        super().__init__(title="Warning", transient_for=parent, flags=0)
        self.present()
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK
        )
        self.set_resizable(False)
        self.set_border_width(10)

        labelhelp = Gtk.Label(label="Are you sure you want to continue?")
        labelhelp.set_justify(Gtk.Justification.CENTER)

        labelhelp1 = Gtk.Label(label=Warnmsg)
        labelhelp1.set_justify(Gtk.Justification.CENTER)
        labelhelp1.set_line_wrap(True)
        labelhelp1.set_max_width_chars(48)
        labelhelp1.set_selectable(True)

        box = self.get_content_area()
        box.add(labelhelp)
        box.add(labelhelp1)
        self.show_all()


class FailDialog(Gtk.Dialog):
    def __init__(self, parent):
        global Failmsg
        super().__init__(title="Fail", transient_for=parent, flags=0)
        self.present()
        self.add_buttons(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        self.set_resizable(False)
        self.set_border_width(10)

        labelhelp = Gtk.Label(label="AltServer has failed.")
        labelhelp.set_justify(Gtk.Justification.CENTER)

        labelhelp1 = Gtk.Label(label=Failmsg)
        labelhelp1.set_justify(Gtk.Justification.CENTER)
        labelhelp1.set_line_wrap(True)
        labelhelp1.set_max_width_chars(48)
        labelhelp1.set_selectable(True)

        box = self.get_content_area()
        box.add(labelhelp)
        box.add(labelhelp1)
        self.show_all()


class Oops(Handy.Window):
    def __init__(self, markup_text, pixbuf_icon):
        super().__init__(title="Error")
        self.present()
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_resizable(False)
        self.set_size_request(450, 100)
        self.set_border_width(10)

        # WindowHandle
        handle = Handy.WindowHandle()
        self.add(handle)
        vb = Gtk.VBox(spacing=0, orientation=Gtk.Orientation.VERTICAL)

        # Headerbar
        self.hb = Handy.HeaderBar()
        self.hb.set_show_close_button(True)
        self.hb.props.title = "Error"
        vb.pack_start(self.hb, False, True, 0)

        pixbuf = Gtk.IconTheme.get_default().load_icon(
            pixbuf_icon, 48, 0
        )
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        image.show()
        image.set_margin_top(10)
        vb.pack_start(image, True, True, 0)

        lbl1 = Gtk.Label()
        lbl1.set_justify(Gtk.Justification.CENTER)
        lbl1.set_markup(markup_text)
        lbl1.set_property("margin_left", 15)
        lbl1.set_property("margin_right", 15)
        lbl1.set_margin_top(10)

        button = Gtk.Button(label="OK")
        button.set_property("margin_left", 125)
        button.set_property("margin_right", 125)
        button.connect("clicked", self.on_info_clicked2)

        handle.add(vb)
        vb.pack_start(lbl1, expand=False, fill=True, padding=0)
        vb.pack_start(button, False, False, 10)
        self.show_all()

    def on_info_clicked2(self, widget):
        quitit()

class SettingsWindow(Handy.Window):
    def __init__(self):
        super().__init__(title="Settings")
        self.present()
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_resizable(False)
        #self.set_size_request(450, 100)
        self.set_border_width(10)

        # WindowHandle
        handle = Handy.WindowHandle()
        self.add(handle)
        vb = Gtk.VBox(spacing=0, orientation=Gtk.Orientation.VERTICAL)

        # Headerbar
        self.hb = Handy.HeaderBar()
        self.hb.set_show_close_button(True)
        self.hb.props.title = "Settings"
        vb.pack_start(self.hb, False, True, 0)

        pixbuf = Gtk.IconTheme.get_default().load_icon(
            "emblem-system-symbolic", 48, 0
        )
        image = Gtk.Image.new_from_pixbuf(pixbuf)
        image.show()
        image.set_margin_top(10)
        vb.pack_start(image, True, True, 0)

        lbl1 = Gtk.Label()
        lbl1.set_justify(Gtk.Justification.CENTER)
        lbl1.set_markup(
            "These settings are experimental. Use at own risk."
        )
        lbl1.set_property("margin_left", 15)
        lbl1.set_property("margin_right", 15)
        lbl1.set_margin_top(10)

        button = Gtk.Button(label="OK")
        button.set_property("margin_left", 125)
        button.set_property("margin_right", 125)
        button.connect("clicked", self.on_info_clicked2)

        button1 = Gtk.Button(label="Open PairWindow")
        button1.set_property("margin_left", 125)
        button1.set_property("margin_right", 125)
        button1.connect("clicked", self.on_info_clicked3)

        handle.add(vb)
        vb.pack_start(lbl1, expand=False, fill=True, padding=0)
        vb.pack_start(button, False, False, 10)
        vb.pack_start(button1, False, False, 10)
        self.show_all()

    def on_info_clicked2(self, widget):
        self.destroy()

    def on_info_clicked3(self, widget):
        openwindow(PairWindow)


# -----------------------------------------------------------------------------

# Main function
def main():
    GLib.set_prgname(APP_NAME)  # Sets the global program name
    Handy.init()
    os.makedirs(altheapath, exist_ok=True)
    global indicator
    indicator = None
    # Update //fork change! Tray mode is now opt-in on Hyprland because repeated tray popup clicks were crashing the compositor
    if should_use_tray():
        indicator = appindicator.Indicator.new(
            "althea-tray-icon",
            resource_path("resources/1.png"),
            appindicator.IndicatorCategory.APPLICATION_STATUS,
        )
        indicator.set_status(appindicator.IndicatorStatus.ACTIVE)
        indicator.set_menu(menu())
        indicator.set_status(appindicator.IndicatorStatus.PASSIVE)
    openwindow(SplashScreen)
    Gtk.main()

# Call main
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Update //fork change! Foreground terminal cancels now stop helper daemons so source runs do not leak background processes
        terminate_althea_services()
        sys.exit(130)
