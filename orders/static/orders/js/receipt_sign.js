(function () {
  const canvas = document.getElementById('receipt-signature-canvas');
  const form = document.getElementById('receipt-sign-form');
  const signatureInput = document.getElementById('id_signature_data');
  const clearButton = document.getElementById('receipt-signature-clear');
  const contactSelect = document.getElementById('id_contact_id');

  if (!canvas || !form || !signatureInput) return;

  const context = canvas.getContext('2d');
  let drawing = false;
  let hasSignature = false;

  function pointFromEvent(event) {
    const rect = canvas.getBoundingClientRect();
    const source = event.touches ? event.touches[0] : event;
    return {
      x: (source.clientX - rect.left) * (canvas.width / rect.width),
      y: (source.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function start(event) {
    event.preventDefault();
    drawing = true;
    const point = pointFromEvent(event);
    context.beginPath();
    context.moveTo(point.x, point.y);
  }

  function move(event) {
    if (!drawing) return;
    event.preventDefault();
    const point = pointFromEvent(event);
    context.lineWidth = 3;
    context.lineCap = 'round';
    context.strokeStyle = '#111827';
    context.lineTo(point.x, point.y);
    context.stroke();
    hasSignature = true;
  }

  function stop(event) {
    if (event) event.preventDefault();
    drawing = false;
  }

  function clearSignature() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    signatureInput.value = '';
    hasSignature = false;
  }

  function fillContactFromSelection() {
    const option = contactSelect?.selectedOptions?.[0];
    if (!option) return;
    document.getElementById('id_contact_name').value = option.dataset.name || '';
    document.getElementById('id_contact_email').value = option.dataset.email || '';
    document.getElementById('id_contact_phone').value = option.dataset.phone || '';
    document.getElementById('id_contact_position').value = option.dataset.position || '';
  }

  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', stop);
  canvas.addEventListener('touchstart', start, { passive: false });
  canvas.addEventListener('touchmove', move, { passive: false });
  canvas.addEventListener('touchend', stop, { passive: false });
  clearButton?.addEventListener('click', clearSignature);
  contactSelect?.addEventListener('change', fillContactFromSelection);
  fillContactFromSelection();

  form.addEventListener('submit', event => {
    if (!hasSignature) {
      event.preventDefault();
      window.alert('Capture la firma antes de continuar.');
      return;
    }
    signatureInput.value = canvas.toDataURL('image/png');
  });
})();
