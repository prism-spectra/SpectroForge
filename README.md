# SpectroForge: The Spectrograph Designer

SpectroForge aids in design and optimization of single-grating spectrographs.
It provides a user-friendly interface to explore various configurations and parameters, enabling users to visualize and analyze the performance of their spectrograph designs.

## Installation
To install SpectroForge, follow these steps:
1. Go to the [Releases](https://github.com/sunipkm/SpectroForge/releases) page and download the latest version for your operating system.
2. Extract the downloaded file.

### Windows
1. Extract the installer executable from the downloaded archive.
2. Run the installer and follow the on-screen instructions to complete the installation.
3. Once installed, you can launch SpectroForge from the Start Menu.

> [!TIP]
> Windows users may need to allow the application to run by clicking "More info" and then "Run anyway" if prompted by Windows Defender SmartScreen.

### macOS
1. Mount the downloaded DMG file by double-clicking it.
2. Drag the SpectroForge application to your Applications folder.
3. You can launch SpectroForge from the Applications folder.

> [!TIP]
> macOS users may need to allow the application to run by going to System Preferences > Security & Privacy > General and clicking "Open Anyway" for SpectroForge.

### Linux
#### Debian/Ubuntu
1. Launch a terminal and navigate to the directory where you downloaded the .deb file.
2. Install the package using the following command:
```bash
sudo dpkg -i spectroforge-<version>.deb
```
3. If there are any dependency issues, run:
```bash
sudo apt-get install -f
```
4. Once installed, you can launch SpectroForge from your application menu.
5. Alternatively, you can run it from the terminal using:
```bash
spectroforge
```
#### Other Linux Distributions
1. Download the `spectroforge-<version>.AppImage` file.
2. Make the AppImage executable by running the following command in the terminal:
```bash
chmod +x spectroforge-<version>.AppImage
```
3. Run the AppImage using the following command:
```bash
./spectroforge-<version>.AppImage
```
4. You can also create a desktop shortcut for easier access.

## Usage
Once you have SpectroForge installed, you can start designing your spectrograph by opening the application, and modifying the parameters in the control panel on the right.

## Documentation
For detailed documentation on how to use SpectroForge, please refer to the [User Guide](https://sunipkm.github.io/SpectroForge/).

## License
SpectroForge is licensed under the SpectroForge Software License. Please see the [LICENSE](LICENSE) file for more details.

> [!IMPORTANT]
> ⚠️ Disclaimer
> **This software is provided "AS IS" without any warranty of any kind.** The software does not come with any guarantees regarding functionality, reliability, or fitness for any particular purpose. Installation and use of this software is at the user's own risk. The author is not responsible for any damage, data loss, or other consequences that may result from the installation or use of this software.
