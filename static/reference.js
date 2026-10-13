'use strict';
let referenceWindow = null, referenceDeadline = 0, referenceUrl = null;
let referenceGeneration = 0, referencePending = false, referenceRetry = 0;

function hideReference() {
  $('reference-preview').hidden = true;
  $('reference-preview').removeAttribute('src');
  if (referenceUrl) URL.revokeObjectURL(referenceUrl);
  referenceUrl = null;
}

function resetReference() {
  referenceGeneration++;
  referenceWindow = null;
  referencePending = false;
  referenceRetry = 0;
  hideReference();
  $('load-reference').disabled = true;
  $('reference-error').textContent = '';
  $('reference-timer').textContent = 'Connecting…';
}

async function syncReference() {
  const generation = referenceGeneration, started = performance.now();
  referencePending = true;
  try {
    const state = await json('/api/reference');
    if (generation !== referenceGeneration) return;
    referenceWindow = state;
    referenceDeadline = started + state.seconds_remaining * 1000;
    $('reference-error').textContent = '';
  } catch (error) {
    if (generation !== referenceGeneration) return;
    referenceWindow = null;
    referenceRetry = performance.now() + 5000;
    $('reference-error').textContent = error.message;
  } finally {
    if (generation === referenceGeneration) referencePending = false;
  }
}

setInterval(() => {
  if (!token) return;
  const remaining = referenceDeadline - performance.now();
  const available = referenceWindow && referenceWindow.available && remaining > 0;
  $('load-reference').disabled = !available;
  if (!available) hideReference();
  $('reference-timer').textContent = referenceWindow && remaining > 0
    ? `${available ? 'Image available for' : 'Next access in'} ${Math.ceil(remaining / 1000)} seconds`
    : 'Checking access window…';
  if ((!referenceWindow || remaining <= 0) && !referencePending && performance.now() >= referenceRetry) {
    syncReference();
  }
}, 250);

$('load-reference').addEventListener('click', () => guard(async () => {
  const generation = referenceGeneration, window = referenceWindow;
  const response = await api('/api/reference/image');
  const blob = await response.blob();
  if (generation !== referenceGeneration || window !== referenceWindow ||
      !window.available || performance.now() >= referenceDeadline) return;
  hideReference();
  referenceUrl = URL.createObjectURL(blob);
  $('reference-preview').src = referenceUrl;
  $('reference-preview').hidden = false;
}));

document.addEventListener('visibilitychange', () => {
  if (document.hidden) hideReference();
  else if (token) resetReference();
});
