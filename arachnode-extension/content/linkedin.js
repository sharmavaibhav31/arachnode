(function() {
  'use strict';
  
  // Listen for messages from the background service worker
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'FILL_MESSAGE') {
      fillMessageBox(msg.draft)
        .then(ok => sendResponse({ ok }))
        .catch(() => sendResponse({ ok: false }));
      return true; // async response
    }
  });
  
  async function fillMessageBox(draft) {
    // Find the message compose area on LinkedIn
    // LinkedIn uses different selectors depending on the page
    const selectors = [
      // Messaging overlay compose box
      'div.msg-form__contenteditable[contenteditable="true"]',
      // Direct message page
      'div.msg-form__contenteditable',
      // Profile message button area after clicking Message
      '.msg-form__contenteditable',
    ];
    
    let box = null;
    
    // Wait up to 8 seconds for the message box to appear
    for (let attempt = 0; attempt < 16; attempt++) {
      for (const sel of selectors) {
        box = document.querySelector(sel);
        if (box) break;
      }
      if (box) break;
      await sleep(500);
    }
    
    if (!box) {
      // Message box not found — this happens if the user needs to 
      // click the Message button first. Store the draft and wait.
      await chrome.storage.local.set({ queued_draft: draft });
      
      // Watch for the Message button and auto-click it
      watchForMessageButton(draft);
      return false;
    }
    
    await fillBox(box, draft);
    return true;
  }
  
  async function fillBox(box, text) {
    // Focus the box
    box.focus();
    box.click();
    
    // Clear existing content
    box.innerHTML = '';
    
    // Small delay to let LinkedIn react
    await sleep(200);
    
    // Use execCommand to insert text (works with contenteditable)
    // This triggers LinkedIn's own input event listeners
    document.execCommand('insertText', false, text);
    
    // Fallback: set innerText directly and dispatch input event
    if (!box.innerText || box.innerText.trim() !== text.trim()) {
      box.innerText = text;
      box.dispatchEvent(new Event('input', { bubbles: true }));
      box.dispatchEvent(new Event('change', { bubbles: true }));
    }
    
    // Highlight the box so user knows it's filled
    box.style.outline = '2px solid #6c47ff';
    box.style.outlineOffset = '2px';
    setTimeout(() => {
      box.style.outline = '';
      box.style.outlineOffset = '';
    }, 2000);
  }
  
  function watchForMessageButton(draft) {
    // Watch for the Message button to appear (profile page)
    // This handles the flow: open profile → click Message → box appears
    const observer = new MutationObserver(async () => {
      const selectors = [
        'div.msg-form__contenteditable[contenteditable="true"]',
        '.msg-form__contenteditable',
      ];
      for (const sel of selectors) {
        const box = document.querySelector(sel);
        if (box) {
          observer.disconnect();
          await sleep(300);
          await fillBox(box, draft);
          await chrome.storage.local.remove('queued_draft');
          return;
        }
      }
    });
    
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });
    
    // Stop watching after 30 seconds
    setTimeout(() => observer.disconnect(), 30000);
  }
  
  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }
  
  // On page load, check if there is a queued draft waiting
  async function checkQueuedDraft() {
    const stored = await chrome.storage.local.get('queued_draft');
    if (stored.queued_draft) {
      await fillMessageBox(stored.queued_draft);
    }
  }
  
  // Check on page load
  if (document.readyState === 'complete') {
    checkQueuedDraft();
  } else {
    window.addEventListener('load', checkQueuedDraft);
  }
  
})();
