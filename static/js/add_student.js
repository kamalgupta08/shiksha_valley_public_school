$(function () {
  var $classSelect = $('#class_name');
  var $preview = $('#fee-preview');
  var $overrideField = $('#override-field');
  var $overrideInput = $('#override_amount');
  var feeMode = $classSelect.closest('form').data('fee-mode') || 'admission';

  function formatRupees(amount) {
    return '₹' + Number(amount).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }

  function loadFeePreview(className) {
    if (!className) {
      $preview.hide();
      $overrideField.hide();
      return;
    }
    $.getJSON('/api/fee-structure/' + encodeURIComponent(className))
      .done(function (fee) {
        var relevantTotal = feeMode === 'promotion' ? fee.total_promotion : fee.total_new_admission;
        var totalLabel = feeMode === 'promotion' ? 'Standard total for this class' : 'Standard total on admission';
        var html = ''
          + (feeMode === 'promotion' ? '' : '<div>Admission Fee: ' + formatRupees(fee.admission_fee) + '</div>')
          + '<div>Tuition Fee (annual): ' + formatRupees(fee.tuition_fee) + '</div>'
          + '<div>Dress Fee: ' + formatRupees(fee.dress_fee) + '</div>'
          + '<div>Book Fee: ' + formatRupees(fee.book_fee) + '</div>'
          + '<div>Misc. Fee: ' + formatRupees(fee.misc_fee) + '</div>'
          + '<div class="total">' + totalLabel + ': ' + formatRupees(relevantTotal) + '</div>';
        $preview.html(html).show();
        $overrideInput.val(relevantTotal);
        $overrideField.show();
      })
      .fail(function () {
        $preview.html('<div>No fee structure set for this class yet. Set it up under Fee Structure.</div>').show();
        $overrideField.hide();
      });
  }

  $classSelect.on('change', function () {
    loadFeePreview($(this).val());
  });

  loadFeePreview($classSelect.val());
});
