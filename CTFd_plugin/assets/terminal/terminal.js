$(function () {
    var terminal = new window.Terminal();
    terminal.open($('#terminal')[0]);

    function resize() {
        $('#terminal').height($('html').outerHeight() - $('nav').outerHeight() - $('footer').outerHeight() - 20);

        setTimeout(() => {
            const MINIMUM_COLS = 2;
            const MINIMUM_ROWS = 1;

            const core = terminal._core;

            const parentElementStyle = window.getComputedStyle(terminal.element.parentElement);
            const parentElementHeight = parseInt(parentElementStyle.getPropertyValue('height'));
            const parentElementWidth = Math.max(0, parseInt(parentElementStyle.getPropertyValue('width')));
            const elementStyle = window.getComputedStyle(terminal.element);
            const elementPadding = {
                top: parseInt(elementStyle.getPropertyValue('padding-top')),
                bottom: parseInt(elementStyle.getPropertyValue('padding-bottom')),
                right: parseInt(elementStyle.getPropertyValue('padding-right')),
                left: parseInt(elementStyle.getPropertyValue('padding-left'))
            };
            const elementPaddingVer = elementPadding.top + elementPadding.bottom;
            const elementPaddingHor = elementPadding.right + elementPadding.left;
            const availableHeight = parentElementHeight - elementPaddingVer;
            const availableWidth = parentElementWidth - elementPaddingHor - core.viewport.scrollBarWidth;
            const geometry = {
                cols: Math.max(MINIMUM_COLS, Math.floor(availableWidth / core._renderService.dimensions.actualCellWidth)),
                rows: Math.max(MINIMUM_ROWS, Math.floor(availableHeight / core._renderService.dimensions.actualCellHeight))
            };

            core._renderService.clear();
            terminal.resize(geometry.cols, geometry.rows);
        }, 0);
    }

    $(window).resize(resize);
    resize();

    var url = new URL('/terminal_ws', window.location.href);
    url.protocol = url.protocol.replace('http', 'ws');

    var socket = new WebSocket(url);
    socket.binaryType = 'arraybuffer';

    terminal.onData((data) => {
        if (socket.readyState == 1) {
            socket.send(data);
        }
    });

    socket.onmessage = (event) => {
        const data = event.data;
        terminal.write(typeof data === 'string' ? data : new Uint8Array(data));
    };

    socket.onclose = (event) => {
        $('#terminal').css('opacity', '0.5');
    };

    socket.onopen = (event) => {
        socket.send('\x03');
    };

    terminal.focus();
});
