// Native <input type="date"> renders using the VISITOR'S OWN browser/OS locale,
// which is why the same page can show mm/dd/yyyy on one computer and dd/mm/yyyy
// on another - it has nothing to do with the server or the HTML value itself.
// flatpickr replaces that native picker with one this site controls directly,
// so every visitor sees the same dd/mm/yyyy format no matter their machine.
//
// The real underlying value submitted with the form stays in Y-m-d (ISO) format
// via the original hidden input - only the visible display changes. No backend
// changes are needed for this to work.

document.addEventListener('DOMContentLoaded', function () {
  if (typeof flatpickr === 'undefined') return;

  document.querySelectorAll('input[type="date"]').forEach(function (el) {
    var maxAttr = el.getAttribute('max');
    var minAttr = el.getAttribute('min');
    flatpickr(el, {
      dateFormat: 'Y-m-d',
      altInput: true,
      altFormat: 'd/m/Y',
      allowInput: true,
      maxDate: maxAttr || undefined,
      minDate: minAttr || undefined,
    });
  });
});
