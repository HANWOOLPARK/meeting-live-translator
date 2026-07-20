# Third-party notices

The Lite ZIP does not redistribute model weights. If the recipient explicitly chooses local translation, the installer downloads the pinned `facebook/m2m100_418M` source revision directly from Hugging Face and converts it locally to CTranslate2 int8.

- M2M100 model: `facebook/m2m100_418M`
- Pinned source revision: `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636`
- Model page: https://huggingface.co/facebook/m2m100_418M
- Pinned source: https://huggingface.co/facebook/m2m100_418M/tree/55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636
- Upstream Fairseq license reference: https://github.com/facebookresearch/fairseq/blob/main/LICENSE
- CTranslate2 conversion documentation: https://opennmt.net/CTranslate2/guides/transformers.html

Python dependencies installed by `setup.bat` and `setup_local_translation.bat` retain their respective upstream licenses and notices.

## Optional native desktop overlay runtime

The Lite ZIP does not redistribute Node.js, Electron, Chromium, or their binary runtime files.
When the recipient explicitly runs `setup_desktop_overlay.bat`, the installer downloads and
installs the following versions only inside that project directory.

- Node.js `v24.18.0`: https://nodejs.org/dist/v24.18.0/
- Node.js license: https://github.com/nodejs/node/blob/v24.18.0/LICENSE
- Electron `43.1.1`: https://www.npmjs.com/package/electron/v/43.1.1
- Electron license: https://github.com/electron/electron/blob/v43.1.1/LICENSE

Node.js and Electron are MIT-licensed projects and include additional upstream notices for bundled
components. Electron's downloaded distribution retains its bundled license files, including the
Chromium third-party license notice. The project-local runtime must not be separated from those
notices when it is copied or redistributed independently of this Lite source package.
