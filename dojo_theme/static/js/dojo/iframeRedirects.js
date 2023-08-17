$(() => {
  let a;
  const getAbsoluteUrl = (url) => {
    if (!a) a = document.createElement('a');
    a.href = url;

    return a.href;
  };

  $("iframe").each(function (i) {
    const src = $(this).attr("src");
    const initialURL = getAbsoluteUrl(src);

    $(this).on("load", function (e) {
      const newURL = e.target.contentWindow.location.href;
      if (newURL != initialURL) {
        window.location.href = newURL;
      }
    });
  });
});
