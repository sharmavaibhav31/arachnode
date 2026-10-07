// When a LinkedIn tab finishes loading, check if there's a 
// pending fill waiting for it

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;
  if (!tab.url || !tab.url.includes('linkedin.com')) return;
  
  // Check if there's a pending fill for this tab
  const stored = await chrome.storage.local.get('pending_fill');
  const pending = stored.pending_fill;
  
  if (!pending || pending.tab_id !== tabId) return;
  
  // Small delay to let LinkedIn's JS initialize
  await sleep(2000);
  
  // Send the draft to the content script
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: 'FILL_MESSAGE',
      draft: pending.draft
    });
  } catch {
    // Content script not ready yet — it will check storage on load
    await chrome.storage.local.set({ queued_draft: pending.draft });
  }
});

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}
