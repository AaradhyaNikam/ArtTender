const API_BASE = '';

async function apiCall(endpoint, method = 'GET', body = null) {
    const headers = {
        'Content-Type': 'application/json'
    };
    
    const token = localStorage.getItem('token');
    if (token) {
        headers['Authorization'] = token; // Simple token format 'UserID_Role'
    }

    const options = {
        method,
        headers
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, options);
    
    let data;
    try {
        data = await response.json();
    } catch(e) {
        throw new Error(`Server Error: ${response.status} ${response.statusText}`);
    }
    
    if (!response.ok) {
        throw new Error(data.detail || 'API Error');
    }
    return data;
}

function checkAuth(requiredRole) {
    const user = JSON.parse(localStorage.getItem('user'));
    if (!user || (requiredRole && user.Role !== requiredRole)) {
        window.location.href = 'index.html';
    }
    return user;
}

function logout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = 'index.html';
}
