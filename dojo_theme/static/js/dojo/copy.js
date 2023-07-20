function copyLinkToClipboard(event) {
    event.preventDefault();
    const linkToCopy = document.getElementById("linkToCopy");

    const tempInput = document.createElement("input");
    tempInput.value = linkToCopy.href;

    document.body.appendChild(tempInput);
    tempInput.select();

    navigator.clipboard.writeText(tempInput.value)
    .then(() => {
        document.body.removeChild(tempInput);
        alert("Link " + linkToCopy.href + " copied!");
    })
    .catch((error) => {
        console.error('Failed to copy link: ', error);
        alert("Copying link failed. Please try again.");
        document.body.removeChild(tempInput);
    });
}
