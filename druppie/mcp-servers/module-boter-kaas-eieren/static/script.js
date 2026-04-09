let gameId = null;
let board = [];
let gameActive = false;

// Initialize the board on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeBoard();
    startNewGame();
});

function initializeBoard() {
    const boardEl = document.getElementById('board');
    boardEl.innerHTML = '';

    for (let i = 0; i < 9; i++) {
        const cell = document.createElement('button');
        cell.className = 'cell';
        cell.dataset.position = i;
        cell.addEventListener('click', handleCellClick);
        boardEl.appendChild(cell);
    }
}

async function startNewGame() {
    try {
        const response = await fetch('/api/new-game', {
            method: 'POST'
        });
        const data = await response.json();

        gameId = data.game_id;
        board = data.board;
        gameActive = data.game_active;

        updateBoard();
        updateStatus(data.result);
    } catch (error) {
        console.error('Error creating new game:', error);
        setStatus('Error starting game');
    }
}

async function handleCellClick(event) {
    const cell = event.target;
    const position = parseInt(cell.dataset.position);

    // Ignore clicks if game is not active or cell is occupied
    if (!gameActive || board[position] !== '') {
        return;
    }

    try {
        const response = await fetch('/api/move', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                game_id: gameId,
                position: position
            })
        });
        const data = await response.json();

        board = data.board;
        gameActive = data.game_active;

        updateBoard();
        updateStatus(data.result);

        // Auto-restart after game over
        if (!gameActive) {
            setTimeout(() => {
                startNewGame();
            }, 2500);
        }
    } catch (error) {
        console.error('Error making move:', error);
        setStatus('Error making move');
    }
}

function updateBoard() {
    const cells = document.querySelectorAll('.cell');
    cells.forEach((cell, index) => {
        cell.textContent = board[index];

        // Remove existing classes
        cell.classList.remove('x', 'o', 'occupied');

        // Add appropriate classes
        if (board[index] === 'X') {
            cell.classList.add('x', 'occupied');
        } else if (board[index] === 'O') {
            cell.classList.add('o', 'occupied');
        }
    });
}

function updateStatus(result) {
    const statusEl = document.getElementById('status');
    statusEl.classList.remove('playing', 'won-x', 'won-o', 'draw');

    if (!gameActive) {
        if (result === 'X_wins') {
            statusEl.textContent = '🎉 You Win! 🎉';
            statusEl.classList.add('won-x');
        } else if (result === 'O_wins') {
            statusEl.textContent = 'AI Wins! 😔';
            statusEl.classList.add('won-o');
        } else if (result === 'draw') {
            statusEl.textContent = "It's a Draw! 🤝";
            statusEl.classList.add('draw');
        }
    } else {
        statusEl.textContent = "Your turn (X)";
        statusEl.classList.add('playing');
    }
}

function setStatus(message) {
    const statusEl = document.getElementById('status');
    statusEl.textContent = message;
    statusEl.classList.remove('playing', 'won-x', 'won-o', 'draw');
}
