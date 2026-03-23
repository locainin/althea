# althea
<img src="https://github.com/vyvir/althea/blob/main/resources/screenshot.png" alt="althea screenshot">

althea is a GUI for AltServer-Linux that allows to easily sideload apps onto an iPhone, an iPad, or an iPod Touch. It supports x86_64, aarch64, and armv7.

This app is in a very early state, so if you're experiencing issues or want to help, you can create a [pull request](https://github.com/vyvir/althea/pulls), [report an issue](https://github.com/vyvir/althea/issues), or join [the Discord server](https://discord.gg/DZwRbyXq5Z).

## Instructions

### Dependencies

Ubuntu:
```
sudo apt install software-properties-common
```

```
sudo add-apt-repository universe -y
```

```
sudo apt-get install binutils python3-pip python3-requests python3-keyring git gir1.2-appindicator3-0.1 usbmuxd libimobiledevice6 libimobiledevice-utils wget curl libavahi-compat-libdnssd-dev zlib1g-dev unzip usbutils libhandy-1-dev gir1.2-notify-0.7 psmisc
```

Fedora:
```
sudo dnf install binutils python3-pip python3-requests python3-keyring git libappindicator-gtk3 usbmuxd libimobiledevice-devel libimobiledevice-utils wget curl avahi-compat-libdns_sd-devel dnf-plugins-core unzip usbutils psmisc libhandy1-devel
```
Arch Linux:
```
sudo pacman -S binutils wget curl git python-pip python-requests python-gobject python-keyring libappindicator-gtk3 usbmuxd libimobiledevice avahi zlib unzip usbutils psmisc libhandy libnotify
```

OpenSUSE:
```
sudo zypper in binutils wget curl git python3-pip python3-requests python3-keyring python3-gobject-Gdk libhandy-devel libappindicator3-1 typelib-1_0-AppIndicator3-0_1 imobiledevice-tools libdns_sd libnotify-devel psmisc
```

### Running althea

Once the dependencies are installed, run the following commands:
```
git clone https://github.com/vyvir/althea
```

```
cd althea
```

```
python3 main.py
```

That's it! Have fun with althea!

## Fork Acknowledgment

This fork exists for personal use on a Hyprland setup.

On Hyprland with Waybar, running `python3 main.py` and then interacting with the tray icon was repeatedly triggering a compositor crash path tied to popup creation and input handling. Because of that, this fork changes the Hyprland behavior to avoid relying on the tray popup flow and instead use a regular window-based control surface.

This fork also includes some source-run quality-of-life fixes, such as cleaning up helper processes correctly when canceling a local `python3 main.py` run.

The upstream project is still the main reference point. This fork should be treated as a personal compatibility and maintenance branch if anything at all. 

The codebase is also fairly messy in places. There are plans to keep doing cleanup work, reduce some of the fragile process handling, and improve general maintainability over time as needed just becausse im bored.

### Fork Changes

- disable tray mode on Hyprland by default and use a normal window-based control flow instead
- keep tray mode available through environment overrides for debugging if needed
- clean up `Ctrl-C` behavior so local `python3 main.py` runs do not leave `AltServer` or `anisette-server` behind
- replace a number of shell-built subprocess calls with safer argument-based process execution
- move sensitive GTK update paths away from worker-thread UI mutation and back onto the main loop
- improve startup and install flow handling so source runs are less fragile overall
- add fork-specific comments in the code where larger behavioral changes were introduced

## FAQ

<b>Fedora 41 shows the following error:</b>

`ERROR: Device returned unhandled error code -5`

You can downgrade crypto policies to the previous Fedora version:

`sudo update-crypto-policies --set LEGACY`

## Credits

althea made by [vyvir](https://github.com/vyvir)

AltServer-Linux made by [NyaMisty](https://github.com/NyaMisty)

Provision by [Dadoum](https://github.com/Dadoum)

Artwork by [Nebula](https://github.com/itsnebulalol)
