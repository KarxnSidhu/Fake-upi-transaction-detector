// Synthetic QA responses. These are never loaded by the shipped frontend.
module.exports = function installFixtures() {
window.__apiMode='partial';window.__historyError=false;window.__healthError=false;window.__fixture={
  "scan_id": 14,
  "verdict": "NEEDS MANUAL CHECK",
  "risk_score": 25,
  "upi_app": "Google Pay",
  "reasons": ["App-specific reference screenshots have not been configured.", "This assessment is based on the checks that could run."],
  "transaction_id": "TEST1234567890123456789012345678901234567890",
  "extracted_text": "SYNTHETIC TEST DATA — NOT A PAYMENT\n<img src=x onerror=alert(1)>\nPayment successful",
  "image_size": "540 × 1080",
  "analysis_quality": "partial",
  "notice": "Confirm the credit in your own bank or UPI app.",
  "checks": {
    "image": {"status": "valid"},
    "ocr": {"status": "available", "message": "Text extracted from test image."},
    "payment_success_text": {"found": true},
    "layout_comparison": {"status": "missing_reference", "note": "No reference screenshots have been installed."},
    "text_consistency": {"status": "analysed", "suspicious": false, "flagged_lines": 0},
    "pixel_anomalies": {"status": "analysed", "suspicious": false, "anomalous_patches": 0},
    "timestamp": {"status": "valid", "reason": "Supported date and time passed syntax checks."},
    "duplicate_image": {"detected": false},
    "duplicate_transaction": {"detected": false}
  }
}
;window.__history=[{id:14,upi_app:'Google Pay',verdict:'NEEDS MANUAL CHECK',risk_score:25,created_at:'2026-11-21T04:00:00Z'},{id:13,upi_app:'PhonePe',verdict:'SUSPICIOUS',risk_score:65,created_at:'2026-11-21T03:00:00Z'},{id:12,upi_app:'Paytm',verdict:'NO OBVIOUS ANOMALY DETECTED',risk_score:0,created_at:'2026-11-20T10:00:00Z'}];window.fetch=async(url,options={})=>{if(url.includes('/health')){if(window.__healthError)throw new TypeError('Offline');return {ok:true,json:async()=>({status:'ok'})};}if(url.includes('/stats'))return {ok:true,json:async()=>({total_scans:3,suspicious_scans:1})};if(url.includes('/history')){if(window.__historyError)throw new TypeError('Offline');return {ok:true,json:async()=>({items:window.__history})};}if(window.__apiMode==='slow')await new Promise((resolve,reject)=>{options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});});if(window.__apiMode==='error')return {ok:false,status:500,json:async()=>({message:'Test server rejected the request. Retry.'})};if(window.__apiMode==='malformed')return {ok:true,json:async()=>({})};let data=structuredClone(window.__fixture);if(window.__apiMode==='missing')data.checks={};if(window.__apiMode==='suspicious'){data.verdict='SUSPICIOUS';data.risk_score=65;data.checks.duplicate_image.detected=true;}if(window.__apiMode==='clear'){data.verdict='NO OBVIOUS ANOMALY DETECTED';data.risk_score=0;data.analysis_quality='heuristic';data.checks.layout_comparison={status:'similar_structure_signal',suspicious:false,note:'Structural similarity found.'};}return {ok:true,json:async()=>data};};
};

