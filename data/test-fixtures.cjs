/* Synthetic full configuration for offline tests only.
 * Never bundled as an App baseline, device record or migration source.
 * Creative RGB arrays come from checked-in works; all seven key layers repeat
 * standard physical base labels instead of personal device readback.
 */
const fs = require('node:fs');
const path = require('node:path');
const read = relative => JSON.parse(fs.readFileSync(path.join(__dirname, relative), 'utf8'));
const designs = ['neon-rift', 'data-storm', 'redline-rush'].map(id => read('designs/' + id + '.design.json'));
const layout = read('keymap-layout.json');
const codes = Array(200).fill('#00000000');
for (const key of layout.keys) codes[key.matrix_index] = key.bindings[0]?.code || '#00000000';
const animation = frames => ({ valid: frames.length ? 1 : 0, frame_num: frames.length,
  frame_data: frames.map((frame_RGB, frame_index) => ({ frame_index, frame_RGB: frame_RGB.slice() })) });
const template = {
  _fixture: true,
  _fixtureNotice: 'Synthetic test data. Never a trusted device baseline.',
  product_info: { product_id: 'CB_FIXTURE' },
  page_num: 8,
  page_data: Array.from({ length: 8 }, (_, page_index) => {
    const design = page_index >= 5 ? designs[page_index - 5] : null;
    return { valid: !!design, page_index, lightness: 100, speed_ms: design?.speed_ms || 40,
      color: { default: false, back_rgb: '#000000', rgb: '#000000' },
      word_page: { valid: 0, word_len: 0, unicode: [] },
      frames: animation(design?.frames || []), keyframes: animation(design?.keyframes || []),
      '//': design?.name || 'Synthetic inactive page ' + page_index };
  }),
  key_layer: { valid: 1, layer_num: 7, layer_data: Array.from({ length: 7 }, () => ({ layer: codes.slice() })) },
  tab_key_num: 0, tab_key: [], macro_key: [], Fn_key_num: 0, Fn_key: [],
  MACRO_key_num: 0, MACRO_key: [], swap_key_num: 0, swap_key: [], exchange_num: 0, exchange_key: [],
  syntheticExtension: { preserved: true }
};
module.exports = () => JSON.parse(JSON.stringify(template));
