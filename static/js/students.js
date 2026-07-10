$(function () {
  var $form = $('#filter-form');

  // Auto-submit whenever a filter dropdown changes
  $('#class_name, #section').on('change', function () {
    $form.trigger('submit');
  });

  // Debounce the free-text search so it doesn't fire on every keystroke
  var searchTimer;
  $('#q').on('input', function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      $form.trigger('submit');
    }, 500);
  });

  function formatRupees(amount) {
    return '₹' + Number(amount).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }

  // Toggle the inline "Collect Fee" panel for a row (closing the remark panel if open)
  $('.toggle-collect').on('click', function () {
    var $row = $(this).closest('tr');
    $row.next('.collect-panel').toggle();
    $row.next('.collect-panel').next('.remark-panel').hide();
  });

  // Toggle the inline "Remark" panel for a row (closing the collect panel if open)
  $('.toggle-remark').on('click', function () {
    var $row = $(this).closest('tr');
    $row.next('.collect-panel').hide();
    $row.next('.collect-panel').next('.remark-panel').toggle();
  });

  // Submit a deposit inline, then update that row's balance without reloading the page
  $('.inline-collect-form').on('submit', function (e) {
    e.preventDefault();
    var $formEl = $(this);
    var $panelRow = $formEl.closest('tr');
    var $studentRow = $panelRow.prev('tr');
    var studentId = $studentRow.data('student-id');
    var $status = $formEl.find('.inline-panel-status');

    $.ajax({
      url: '/students/' + studentId + '/deposit',
      method: 'POST',
      data: $formEl.serialize(),
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).done(function (resp) {
      var $balanceCell = $studentRow.find('.balance-cell');
      $balanceCell.text(formatRupees(resp.balance));
      $balanceCell.toggleClass('due', resp.balance > 0);
      $balanceCell.toggleClass('clear', resp.balance <= 0);
      $status.text('Saved.').css('color', 'var(--green-ok)');
      $formEl[0].reset();
      setTimeout(function () {
        $panelRow.hide();
        $status.text('');
      }, 900);
    }).fail(function (xhr) {
      var msg = (xhr.responseJSON && xhr.responseJSON.error) || 'Could not save deposit.';
      $status.text(msg).css('color', 'var(--red)');
    });
  });

  // Submit a remark inline, then show it under the student's name without reloading
  $('.inline-remark-form').on('submit', function (e) {
    e.preventDefault();
    var $formEl = $(this);
    var $panelRow = $formEl.closest('tr');
    var $studentRow = $panelRow.prev('tr').prev('tr'); // collect-panel row sits in between
    var studentId = $studentRow.data('student-id');
    var $status = $formEl.find('.inline-panel-status');

    $.ajax({
      url: '/students/' + studentId + '/note',
      method: 'POST',
      data: $formEl.serialize(),
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).done(function (resp) {
      var $remarkDiv = $studentRow.find('.row-remark');
      $remarkDiv.text(resp.note).show();
      $status.text('Saved.').css('color', 'var(--green-ok)');
      $formEl[0].reset();
      setTimeout(function () {
        $panelRow.hide();
        $status.text('');
      }, 900);
    }).fail(function (xhr) {
      var msg = (xhr.responseJSON && xhr.responseJSON.error) || 'Could not save remark.';
      $status.text(msg).css('color', 'var(--red)');
    });
  });
});
