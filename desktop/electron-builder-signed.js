'use strict';
const base=require('./package.json').build;
// The signed metadata is renamed into app.asar/release-mode.json, exactly where
// release-mode.js loads it. It is deliberately not an external mutable resource.
module.exports={
 ...base,
 files:[...base.files.filter(x=>x!=='release-mode.json'),{from:'release-mode-signed.json',to:'release-mode.json'}],
 win:{...base.win,verifyUpdateCodeSignature:true},
};
