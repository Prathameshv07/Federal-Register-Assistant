// DOM Elements
const chatForm = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const messagesContainer = document.getElementById('chat-messages');
const suggestionsContainer = document.getElementById('suggestions-container');
const voiceInputButton = document.getElementById('voice-input-btn');
const documentPreview = document.getElementById('document-preview');
const closePreviewButton = document.getElementById('close-preview');
const loadingOverlay = document.getElementById('loading-overlay');
const demoScenarioButtons = document.querySelectorAll('.demo-scenarios button');

// Stats and charts elements
const dataFreshnessEl = document.getElementById('data-freshness');
const totalDocumentsEl = document.getElementById('total-documents');
const dateRangeEl = document.getElementById('date-range');
const queryTimeEl = document.getElementById('query-time');
const toolsUsedEl = document.getElementById('tools-used');
const documentTypesChart = document.getElementById('document-types-chart');
const timelineChart = document.getElementById('timeline-chart');

// Global state
let socket;
let messageId = 0;
let documentTypesPieChart;
let isVoiceInputActive = false;
let recognition;
let statsLoaded = false;  // Track if stats have already been loaded

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    initCharts();
    loadDatabaseStats();
    initSpeechRecognition();
    
    // Set up event listeners
    chatForm.addEventListener('submit', handleChatSubmit);
    voiceInputButton.addEventListener('click', toggleVoiceInput);
    closePreviewButton.addEventListener('click', hideDocumentPreview);
    demoScenarioButtons.forEach(button => {
        button.addEventListener('click', handleDemoScenario);
    });
    
    // Prevent sidebar scrolling issues
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
        // Stop any potential scroll momentum
        sidebar.addEventListener('wheel', (e) => {
            // Only allow normal scroll behavior, prevent momentum scrolling
            const isScrollingDown = e.deltaY > 0;
            const isAtBottom = sidebar.scrollTop + sidebar.clientHeight >= sidebar.scrollHeight;
            const isAtTop = sidebar.scrollTop === 0;
            
            // Prevent scroll if we're at the boundaries
            if ((isScrollingDown && isAtBottom) || (!isScrollingDown && isAtTop)) {
                e.preventDefault();
            }
        });
    }
    
    // Show demo modal after 1 second (optional)
    setTimeout(() => {
        const demoModal = new bootstrap.Modal(document.getElementById('demo-modal'));
        demoModal.show();
    }, 2000);
    
    // Hide loading overlay
    setTimeout(() => {
        loadingOverlay.style.opacity = 0;
        setTimeout(() => {
            loadingOverlay.style.display = 'none';
        }, 500);
    }, 1500);
});

// Initialize WebSocket connection
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;
    
    socket = new WebSocket(wsUrl);
    
    socket.onopen = () => {
        console.log('WebSocket connected');
    };
    
    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleSocketMessage(data);
    };
    
    socket.onclose = () => {
        console.log('WebSocket disconnected');
        // Try to reconnect after 3 seconds
        setTimeout(initWebSocket, 3000);
    };
    
    socket.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

// Handle WebSocket messages
function handleSocketMessage(data) {
    switch (data.type) {
        case 'assistant_message':
            updateAssistantMessage(data);
            processMetadata(data.metadata);
            break;
            
        case 'thinking':
            addThinkingIndicator(data.id);
            break;
            
        case 'suggestions':
            displaySuggestions(data.suggestions);
            break;
            
        default:
            console.log('Unknown message type:', data.type);
    }
    
    // Scroll to bottom of chat
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Handle chat form submission
function handleChatSubmit(event) {
    event.preventDefault();
    
    const message = userInput.value.trim();
    if (!message) return;
    
    // Disable input until response is received
    userInput.value = '';
    userInput.disabled = true;
    
    // Add user message to chat
    addUserMessage(message);
    
    // Send message to WebSocket
    socket.send(JSON.stringify({
        type: 'user_message',
        content: message,
        id: messageId
    }));
    
    // Clear suggestions
    suggestionsContainer.innerHTML = '';
    
    // Increment message ID for next message pair
    messageId++;
    
    // Re-enable input
    userInput.disabled = false;
    userInput.focus();
}

// Add user message to chat
function addUserMessage(content) {
    const messageEl = document.createElement('div');
    messageEl.classList.add('message', 'user-message');
    messageEl.textContent = content;
    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Add thinking indicator
function addThinkingIndicator(id) {
    const existingIndicator = document.querySelector(`.thinking[data-id="${id}"]`);
    if (existingIndicator) return;
    
    const messageEl = document.createElement('div');
    messageEl.classList.add('message', 'thinking');
    messageEl.setAttribute('data-id', id);
    messageEl.textContent = 'Thinking';
    
    const dotsContainer = document.createElement('div');
    dotsContainer.classList.add('dots');
    
    for (let i = 0; i < 3; i++) {
        const dot = document.createElement('div');
        dot.classList.add('dot');
        dotsContainer.appendChild(dot);
    }
    
    messageEl.appendChild(dotsContainer);
    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Update or add assistant message
function updateAssistantMessage(data) {
    const existingThinking = document.querySelector(`.thinking[data-id="${data.id}"]`);
    
    if (existingThinking) {
        // Replace thinking indicator with actual message
        const messageEl = document.createElement('div');
        messageEl.classList.add('message', 'assistant-message');
        messageEl.setAttribute('data-id', data.id);
        
        // Process content for document links
        const processedContent = processDocumentLinks(data.content);
        messageEl.innerHTML = processedContent;
        
        messagesContainer.replaceChild(messageEl, existingThinking);
        
        // Process metadata here as well to ensure it's updated when message appears
        processMetadata(data.metadata);
    } else {
        // Check if we already have this message (update case)
        const existingMessage = document.querySelector(`.assistant-message[data-id="${data.id}"]`);
        
        if (existingMessage) {
            // Update existing message
            const processedContent = processDocumentLinks(data.content);
            existingMessage.innerHTML = processedContent;
        } else {
            // Add new message
            const messageEl = document.createElement('div');
            messageEl.classList.add('message', 'assistant-message');
            messageEl.setAttribute('data-id', data.id);
            
            const processedContent = processDocumentLinks(data.content);
            messageEl.innerHTML = processedContent;
            
            messagesContainer.appendChild(messageEl);
        }
    }
    
    // Scroll to the bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Process content for document links
function processDocumentLinks(content) {
    // Regular expression to find Federal Register document mentions
    const regex = /document number ([A-Z0-9-]+)/gi;
    
    // Replace with clickable links
    return content.replace(regex, (match, docNumber) => {
        return `${match} <span class="document-link" onclick="showDocumentPreview('${docNumber}')">
            <i class="fas fa-external-link-alt icon"></i> View Document
        </span>`;
    });
}

// Display query suggestions
function displaySuggestions(suggestions) {
    if (!suggestions || suggestions.length === 0) {
        suggestionsContainer.innerHTML = '';
        return;
    }
    
    suggestionsContainer.innerHTML = `
        <p><small>You might also want to ask:</small></p>
        <div class="suggestion-chips"></div>
    `;
    
    const chipsContainer = suggestionsContainer.querySelector('.suggestion-chips');
    
    suggestions.forEach(suggestion => {
        const chip = document.createElement('div');
        chip.classList.add('suggestion-chip');
        chip.textContent = suggestion;
        chip.addEventListener('click', () => {
            userInput.value = suggestion;
            suggestionsContainer.innerHTML = '';
            chatForm.dispatchEvent(new Event('submit'));
        });
        
        chipsContainer.appendChild(chip);
    });
}

// Process metadata from response
function processMetadata(metadata) {
    if (!metadata) return;
    
    // Update query time
    if (metadata.query_time) {
        queryTimeEl.textContent = `${metadata.query_time.toFixed(2)}s`;
    } else {
        queryTimeEl.textContent = "-";
    }
    
    // Update tools used
    if (metadata.tools_used) {
        if (metadata.tools_used.length === 0) {
            // Don't change the value if there are no tools used
            // This fixes the issue where tools used was being reset to "None"
        } else {
            // Convert tool names to friendlier display names
            const displayNames = {
                'query_federal_register': 'Database Search',
                'get_database_statistics': 'Statistics',
                'suggest_related_queries': 'Query Suggestions'
            };
            
            const toolNames = metadata.tools_used.map(tool => displayNames[tool] || tool);
            toolsUsedEl.textContent = toolNames.join(', ');
        }
    } else {
        // Only set to "-" if this is the initial state
        if (toolsUsedEl.textContent === "" || toolsUsedEl.textContent === "-") {
            toolsUsedEl.textContent = "-";
        }
    }
}

// Show document preview panel
window.showDocumentPreview = function(documentNumber) {
    // Set loading state
    documentPreview.classList.add('active');
    document.getElementById('preview-title').textContent = `Document ${documentNumber}`;
    document.getElementById('preview-meta').textContent = 'Loading...';
    document.getElementById('preview-abstract').textContent = '';
    document.getElementById('preview-html-link').href = '#';
    document.getElementById('preview-pdf-link').href = '#';
    
    // Send a socket message to get document details
    // In a real implementation, we'd make an API call here
    // For demo, we'll simulate with a timeout
    setTimeout(() => {
        // Simulate document data - ensure document_type is always specified
        const documentData = {
            document_number: documentNumber,
            title: `Executive Order ${documentNumber}: Federal Regulation Policy`,
            publication_date: new Date().toISOString().split('T')[0],
            document_type: 'executive_order',  // Always specify a document type
            abstract: 'This executive order establishes policies and procedures for federal regulations, ensuring they serve the public interest, promote economic growth, and are based on sound scientific evidence.',
            html_url: `https://www.federalregister.gov/documents/${documentNumber}`,
            pdf_url: `https://www.federalregister.gov/documents/${documentNumber}/pdf`
        };
        
        // Update preview panel
        document.getElementById('preview-title').textContent = documentData.title;
        
        // Format the document type properly and ensure it's never displayed as "unspecified"
        let displayType = documentData.document_type;
        if (!displayType || displayType === 'unspecified') {
            // Try to infer type from title
            if (documentData.title.toLowerCase().includes('executive order')) {
                displayType = 'executive_order';
            } else if (documentData.title.toLowerCase().includes('notice')) {
                displayType = 'notice';
            } else if (documentData.title.toLowerCase().includes('proposed rule')) {
                displayType = 'proposed_rule';
            } else if (documentData.title.toLowerCase().includes('rule')) {
                displayType = 'rule';
            } else {
                displayType = 'presidential_document';
            }
        }
        
        // Format the type for display
        const formattedType = displayType
            .replace(/_/g, ' ')
            .replace(/\b\w/g, c => c.toUpperCase());
            
        document.getElementById('preview-meta').innerHTML = `
            <div><strong>Document Number:</strong> ${documentData.document_number}</div>
            <div><strong>Publication Date:</strong> ${documentData.publication_date}</div>
            <div><strong>Type:</strong> ${formattedType}</div>
        `;
        document.getElementById('preview-abstract').textContent = documentData.abstract;
        document.getElementById('preview-html-link').href = documentData.html_url;
        document.getElementById('preview-pdf-link').href = documentData.pdf_url;
    }, 500);
}

// Hide document preview panel
function hideDocumentPreview() {
    documentPreview.classList.remove('active');
}

// Initialize charts
function initCharts() {
    // Document types pie chart
    const ctx = documentTypesChart.getContext('2d');
    documentTypesPieChart = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: ['Loading...'],
            datasets: [{
                data: [1],
                backgroundColor: ['#6c757d'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,  // Disable animations entirely
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: 'white',
                        font: {
                            size: 10
                        }
                    }
                }
            }
        }
    });
    
    // Timeline chart (using Plotly.js)
    Plotly.newPlot(timelineChart, [{
        x: [new Date()],
        y: [0],
        type: 'scatter',
        mode: 'lines',
        line: {
            color: '#4ECDC4',
            width: 2
        }
    }], {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: {
            color: 'white'
        },
        margin: {
            l: 40,
            r: 20,
            b: 40,
            t: 10
        },
        xaxis: {
            title: 'Date',
            color: 'white'
        },
        yaxis: {
            title: 'Documents',
            color: 'white'
        },
        height: 200,
        staticPlot: true  // Make the plot static to prevent interactions causing scroll
    }, {
        displayModeBar: false
    });
}

// Load database statistics
function loadDatabaseStats() {
    // Prevent multiple loads which could cause UI jitter
    if (statsLoaded) return;
    
    fetch('/api/database/stats')
        .then(response => response.json())
        .then(data => {
            updateDatabaseStats(data);
            updateCharts(data);
            updateDataFreshness(data);
            statsLoaded = true;  // Mark stats as loaded
        })
        .catch(error => {
            console.error('Error loading database stats:', error);
        });
}

// Update database statistics display
function updateDatabaseStats(data) {
    totalDocumentsEl.textContent = data.total_documents.toLocaleString();
    
    if (data.date_range && data.date_range.min && data.date_range.max) {
        const minDate = new Date(data.date_range.min).toLocaleDateString();
        const maxDate = new Date(data.date_range.max).toLocaleDateString();
        dateRangeEl.textContent = `${minDate} - ${maxDate}`;
    } else {
        dateRangeEl.textContent = 'N/A';
    }
}

// Update charts with database data
function updateCharts(data) {
    // Update document types pie chart
    if (data.document_types && Object.keys(data.document_types).length > 0) {
        const labels = [];
        const values = [];
        const colors = [
            '#4ECDC4', '#FF6B6B', '#FFA726', '#42A5F5', 
            '#9CCC65', '#7E57C2', '#EC407A', '#26A69A'
        ];
        
        Object.entries(data.document_types).forEach(([type, count], index) => {
            // Format label for display and handle null values
            let formattedType = type;
            if (type === null || type === undefined || type === 'null') {
                formattedType = 'Unspecified';
            } else {
                formattedType = type
                    .replace(/_/g, ' ')
                    .replace(/\b\w/g, c => c.toUpperCase());
            }
                
            labels.push(formattedType);
            values.push(count);
        });
        
        // Only update the chart if there's valid data to prevent rendering issues
        if (labels.length > 0 && values.length > 0) {
            documentTypesPieChart.data.labels = labels;
            documentTypesPieChart.data.datasets[0].data = values;
            documentTypesPieChart.data.datasets[0].backgroundColor = colors.slice(0, labels.length);
            
            // Disable animations to prevent layout shifts
            documentTypesPieChart.options.animation = false;
            
            documentTypesPieChart.update();
        }
    }
    
    // Timeline chart (using Plotly.js)
    // In a real implementation, we would have time series data
    // For demo purposes, we'll generate some fake data
    const today = new Date();
    const dates = [];
    const counts = [];
    
    // Generate 30 days of data
    for (let i = 30; i >= 0; i--) {
        const date = new Date(today);
        date.setDate(date.getDate() - i);
        dates.push(date);
        
        // Generate a random count between 5 and 30
        const count = Math.floor(Math.random() * 25) + 5;
        counts.push(count);
    }
    
    // Update the Plotly chart without animations
    Plotly.update(timelineChart, {
        x: [dates],
        y: [counts]
    }, {
        // Disable animations
        transition: {
            duration: 0
        }
    }, [0]);
}

// Update data freshness indicator
function updateDataFreshness(data) {
    if (!data.last_update) {
        dataFreshnessEl.innerHTML = '<span class="dot red"></span> No data';
        return;
    }
    
    const lastUpdate = new Date(data.last_update);
    const now = new Date();
    const diffDays = Math.floor((now - lastUpdate) / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) {
        dataFreshnessEl.innerHTML = '<span class="dot green"></span> Updated Today';
    } else if (diffDays === 1) {
        dataFreshnessEl.innerHTML = '<span class="dot yellow"></span> Updated Yesterday';
    } else {
        dataFreshnessEl.innerHTML = `<span class="dot red"></span> Updated ${diffDays} days ago`;
    }
}

// Handle demo scenario selection
function handleDemoScenario(event) {
    const query = event.target.getAttribute('data-query');
    if (query) {
        userInput.value = query;
        chatForm.dispatchEvent(new Event('submit'));
        
        // Close the modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('demo-modal'));
        modal.hide();
    }
}

// Initialize speech recognition for voice input
function initSpeechRecognition() {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        // Create speech recognition object
        recognition = new (window.webkitSpeechRecognition || window.SpeechRecognition)();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';
        
        recognition.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            userInput.value = transcript;
            isVoiceInputActive = false;
            voiceInputButton.classList.remove('btn-danger');
            voiceInputButton.classList.add('btn-secondary');
        };
        
        recognition.onend = function() {
            isVoiceInputActive = false;
            voiceInputButton.classList.remove('btn-danger');
            voiceInputButton.classList.add('btn-secondary');
        };
        
        recognition.onerror = function(event) {
            console.error('Speech recognition error:', event.error);
            isVoiceInputActive = false;
            voiceInputButton.classList.remove('btn-danger');
            voiceInputButton.classList.add('btn-secondary');
        };
    } else {
        // Browser doesn't support speech recognition
        voiceInputButton.style.display = 'none';
    }
}

// Toggle voice input
function toggleVoiceInput() {
    if (!recognition) return;
    
    if (isVoiceInputActive) {
        recognition.stop();
        isVoiceInputActive = false;
        voiceInputButton.classList.remove('btn-danger');
        voiceInputButton.classList.add('btn-secondary');
    } else {
        recognition.start();
        isVoiceInputActive = true;
        voiceInputButton.classList.remove('btn-secondary');
        voiceInputButton.classList.add('btn-danger');
    }
} 