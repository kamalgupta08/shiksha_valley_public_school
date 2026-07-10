$(function () {
  var $classSelect = $('#class_name');
  var $preview = $('#fee-preview');

  function formatRupees(amount) {
    return '₹' + Number(amount).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }

  function loadFeePreview(className) {
    if (!className) {
      $preview.hide();
      return;
    }
    $.getJSON('/api/fee-structure/' + encodeURIComponent(className))
      .done(function (fee) {
        var html = ''
          + '<div>Admission Fee: ' + formatRupees(fee.admission_fee) + '</div>'
          + '<div>Tuition Fee (annual): ' + formatRupees(fee.tuition_fee) + '</div>'
          + '<div>Dress Fee: ' + formatRupees(fee.dress_fee) + '</div>'
          + '<div>Book Fee: ' + formatRupees(fee.book_fee) + '</div>'
          + '<div>Misc. Fee: ' + formatRupees(fee.misc_fee) + '</div>'
          + '<div class="total">Total due on admission: ' + formatRupees(fee.total_new_admission) + '</div>';
        $preview.html(html).show();
      })
      .fail(function () {
        $preview.html('<div>No fee structure set for this class yet. Set it up under Fee Structure.</div>').show();
      });
  }

  $classSelect.on('change', function () {
    loadFeePreview($(this).val());
  });
});
