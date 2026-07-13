$(function () {
  $('#class_name').on('change', function () {
    var className = $(this).val();
    if (!className) {
      return;
    }
    $.getJSON('/api/fee-structure/' + encodeURIComponent(className))
      .done(function (fee) {
        $('#admission_fee').val(fee.admission_fee);
        $('#tuition_fee').val(fee.tuition_fee);
        $('#dress_fee').val(fee.dress_fee);
        $('#book_fee').val(fee.book_fee);
        $('#misc_fee').val(fee.misc_fee);
      })
      .fail(function () {
        // No fee row yet for this class (shouldn't normally happen) — leave fields blank for entry.
        $('#admission_fee, #tuition_fee, #dress_fee, #book_fee, #misc_fee').val('');
      });
  });
});
