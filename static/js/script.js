function searchFriends() {
    const query = document.getElementById('search').value;
    fetch(`/search_users?q=${query}`)
        .then(response => response.json())
        .then(users => {
            const searchResults = document.getElementById('search-results');
            searchResults.innerHTML = '';
            users.forEach(user => {
                const li = document.createElement('li');
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = '/add_friend';
                form.className = 'flex justify-between items-center p-3 bg-gray-100 rounded-2xl shadow-sm hover:bg-purple-50 transition-all duration-300 animate-slide-in';
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'friend';
                input.value = user;
                const span = document.createElement('span');
                span.textContent = user;
                span.className = 'text-gray-700';
                const button = document.createElement('button');
                button.textContent = 'Add';
                button.className = 'bg-purple-500 text-white px-4 py-1 rounded-xl hover:bg-purple-600 transition-all duration-300 font-semibold shadow-md';
                form.appendChild(input);
                form.appendChild(span);
                form.appendChild(button);
                li.appendChild(form);
                searchResults.appendChild(li);
            });
        });
}

function sendMessage(recipient) {
    const message = document.getElementById('message').value;
    if (message) {
        socket.emit('message', { recipient: recipient, message: message });
        document.getElementById('message').value = '';
    }
}

function toggleEmojiPicker() {
    const picker = document.getElementById('emoji-picker');
    picker.classList.toggle('hidden');
}

function sendTyping(recipient) {
    const message = document.getElementById('message').value;
    socket.emit('typing', { recipient: recipient, typing: message.length > 0 });
}