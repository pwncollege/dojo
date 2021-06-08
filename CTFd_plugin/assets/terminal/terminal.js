$(function () {
    var url = new URL('/terminal_ws', window.location.href);
    url.protocol = url.protocol.replace('http', 'ws');
    const webSocket = new WebSocket(url);

    const terminal = new Terminal({
        fontFamily: "'Source Code Pro', monospace",
        theme: {
            foreground: '#dcdfe4',
            background: '#282c34',
            cursor: '#a3b3cc',
            black: '#282c34',
            brightBlack: '#282c34',
            red: '#e06c75',
            brightRed: '#e06c75',
            green: '#98c379',
            brightGreen: '#98c379',
            yellow: '#e5c07b',
            brightYellow: '#e5c07b',
            blue: '#61afef',
            brightBlue: '#61afef',
            magenta: '#c678dd',
            brightMagenta: '#c678dd',
            cyan: '#56b6c2',
            brightCyan: '#56b6c2',
            white: '#dcdfe4',
            brightWhite: '#dcdfe4'
        }
    });
    const fitAddon = new FitAddon.FitAddon();
    const attachAddon = new AttachAddon.AttachAddon(webSocket);
    terminal.loadAddon(fitAddon);
    terminal.loadAddon(attachAddon);
    terminal.open(document.getElementById('terminal'));

    function resize() {
        fitAddon.fit();
        var params = {
            width: terminal.cols,
            height: terminal.rows,
        };
        CTFd.fetch("/pwncollege_api/v1/terminal/resize", {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        }).then(function (response) {
            return response.json();
        }).then(function (result) {
        });
    }

    window.onresize = () => {
        resize();
    }
    resize();

    webSocket.onopen = (event) => {
        webSocket.send('\x0c');
    };
    webSocket.onclose = (event) => {
        $('#terminal').css('opacity', '0.5');
    };
    setInterval(() => webSocket.send(''), 5000);

    terminal.focus();
});
