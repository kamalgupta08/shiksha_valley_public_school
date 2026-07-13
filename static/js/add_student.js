$(function () {
  var $classSelect = $('#class_name');
  var $feeSection = $('#fee-section');
  var $totalPreview = $('#fee-total-preview');
  var $admissionFee = $('#admission_fee');   // only present in admission mode
  var $tuitionDisplay = $('#tuition_fee_display');
  var $dressFee = $('#dress_fee');
  var $bookFee = $('#book_fee');
  var $miscFee = $('#misc_fee');
  var feeMode = $classSelect.closest('form').data('fee-mode') || 'admission';
  var fixedTuition = 0;

  function formatRupees(amount) {
    return '₹' + Number(amount || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }

  function num(val) {
    var n = parseFloat(val);
    return isNaN(n) ? 0 : n;
  }

  function updateTotal() {
    var total = num($dressFee.val()) + num($bookFee.val()) + num($miscFee.val());
    var html;
    if (feeMode === 'admission') {
      total += fixedTuition + num($admissionFee.val());
      html = '<div class="total">Total due now (incl. this month\'s tuition): ' + formatRupees(total) + '</div>'
           + '<div>Tuition then recurs automatically every month: ' + formatRupees(fixedTuition) + '/month</div>';
    } else {
      html = '<div class="total">Total due now (one-time fees only): ' + formatRupees(total) + '</div>'
           + '<div>New monthly tuition rate: ' + formatRupees(fixedTuition) + '/month, starting the next unbilled month</div>';
    }
    $totalPreview.html(html).show();
  }

  function loadFeeDefaults(className) {
    if (!className) {
      $feeSection.hide();
      return;
    }
    $.getJSON('/api/fee-structure/' + encodeURIComponent(className))
      .done(function (fee) {
        fixedTuition = fee.tuition_fee;
        $tuitionDisplay.val(formatRupees(fee.tuition_fee) + ' / month');
        if (feeMode === 'admission') {
          $admissionFee.val(fee.admission_fee);
        }
        $dressFee.val(fee.dress_fee);
        $bookFee.val(fee.book_fee);
        $miscFee.val(fee.misc_fee);
        $feeSection.show();
        updateTotal();
      })
      .fail(function () {
        $totalPreview.html('<div>No fee structure set for this class yet. Set it up under Fee Structure.</div>').show();
        $feeSection.show();
      });
  }

  $classSelect.on('change', function () {
    loadFeeDefaults($(this).val());
  });

  $dressFee.on('input', updateTotal);
  $bookFee.on('input', updateTotal);
  $miscFee.on('input', updateTotal);
  if (feeMode === 'admission') {
    $admissionFee.on('input', updateTotal);
  }

  loadFeeDefaults($classSelect.val());
});
