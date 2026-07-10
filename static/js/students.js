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
});
