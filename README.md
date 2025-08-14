# Natural Language Filter Agent

A single API endpoint that accepts natural language filter requests and returns structured filter objects, designed for seamless UI chatbot integration.

## Features

- **Single API Integration**: One endpoint handles all filter logic for easy UI integration
- **Conversational Interface**: Natural language input with intelligent responses  
- **Auto-Resolution**: Automatically fetches and validates filter values internally
- **Fallback Handling**: Provides suggestions when exact matches aren't found

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repository-url>
cd og_filter

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Copy the example environment file and configure your settings:

```bash
cp env.example .env
```

Edit `.env` and set the required configuration:

```bash
# Required: OpenAI API Key
OPENAI_API_KEY=your-openai-api-key-here

# Optional: Filter API configuration (uses defaults if not set)
FILTER_API_BASE_URL=http://controlpanel.ogov.me/api/reporting_service/next
FILTER_API_AUTH_TOKEN=your-filter-api-token
```

### 3. Run the Application

```bash
# Development mode
python run.py

# Or using uvicorn directly
uvicorn src.natural_language_filter.api.main:app --reload
```

The API will be available at `http://localhost:8000`

- API Documentation: `http://localhost:8000/docs`
- Alternative docs: `http://localhost:8000/redoc`

## API Usage

### Single Endpoint

```
POST /api/filters/natural-language
```

### Request Format

```json
{
  "query": "Show me accounts with type 'Accounts Payable' for fiscal period 10",
  "available_filters": [
    {"name": "account_type", "label": "Account Type", "type": "lens"},
    {"name": "fiscal_period", "label": "Fiscal Period", "type": "lens"}
  ],
  "delphi_session": "your-session-token-here",
  "conversation_id": "conv_123",
  "context": {}
}
```

### Response Types

#### Success Response
```json
{
  "type": "success",
  "message": "Applied filters for Account Type = 'Accounts Payable' and Fiscal Period = '10'",
  "filters": [
    {
      "operator": "and",
      "value": [
        {
          "column_name": "account_type",
          "value": "Accounts Payable", 
          "operator": "equal"
        }
      ],
      "source_type": "lens"
    }
  ],
  "conversation_id": "conv_123"
}
```

#### Clarification Response
```json
{
  "type": "clarification",
  "message": "I couldn't find exact matches for some values. Please choose from available options:",
  "clarifications": [
    {
      "filter_name": "account_type",
      "user_input": "Checking Account", 
      "available_values": ["Accounts Payable", "Accounts Receivable", "Cash", "Inventory"]
    }
  ],
  "conversation_id": "conv_123"
}
```

#### Error Response
```json
{
  "type": "error",
  "message": "Filter 'invalid_filter' not found in available filters",
  "error_code": "FILTER_NOT_FOUND",
  "conversation_id": "conv_123"
}
```

## Examples

### Basic Filter Request

```javascript
const response = await fetch('/api/filters/natural-language', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: "Show accounts with type 'Cash' and fiscal period 10",
    available_filters: [
      {"name": "account_type", "label": "Account Type", "type": "lens"},
      {"name": "fiscal_period", "label": "Fiscal Period", "type": "lens"}
    ]
  })
});

const result = await response.json();

if (result.type === 'success') {
  // Apply filters to your data
  console.log('Filters:', result.filters);
} else if (result.type === 'clarification') {
  // Show options to user
  console.log('Need clarification:', result.clarifications);
} else {
  // Handle error
  console.error('Error:', result.message);
}
```

### Multi-turn Conversation

```javascript
// First request
let response1 = await fetch('/api/filters/natural-language', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: "Filter by account type 'Checking'",
    available_filters: [...],
    conversation_id: "conv_124"
  })
});

// If clarification needed
if (response1.type === 'clarification') {
  // User selects "Cash" from suggestions
  
  // Follow-up request
  let response2 = await fetch('/api/filters/natural-language', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: "Use 'Cash' for account type",
      available_filters: [...],
      conversation_id: "conv_124"  // Same conversation
    })
  });
}
```

## Architecture

```
┌─────────────────┐    POST /api/filters/natural-language    ┌─────────────────┐
│                 │ ────────────────────────────────────────► │                 │
│   UI Chatbot    │                                           │  Filter Agent   │
│                 │ ◄──────────────────────────────────────── │   (Single API)  │
└─────────────────┘              JSON Response               └─────────────────┘
                                                                        │
                                                                        │ Internal Calls
                                                                        ▼
                                                              ┌─────────────────┐
                                                              │  Reporting API  │
                                                              │ (Filter Values) │
                                                              └─────────────────┘
```

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `OPENAI_API_KEY` | OpenAI API key | - | ✅ |
| `OPENAI_MODEL` | OpenAI model to use | `gpt-4` | ❌ |
| `FILTER_API_BASE_URL` | Reporting service base URL | `http://controlpanel.ogov.me/api/reporting_service/next` | ❌ |
| `FILTER_API_AUTH_TOKEN` | Auth token for reporting service | - | ❌ |
| `API_HOST` | API host address | `0.0.0.0` | ❌ |
| `API_PORT` | API port number | `8000` | ❌ |
| `DEBUG` | Enable debug mode | `false` | ❌ |
| `LOG_LEVEL` | Logging level | `INFO` | ❌ |

### Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Format code
black src/
isort src/
```

## Deployment

### Production

```bash
# Install production dependencies only
pip install -r requirements.txt

# Set production environment variables
export ENVIRONMENT=production
export DEBUG=false
export OPENAI_API_KEY=your-production-key

# Run with gunicorn (recommended)
gunicorn src.natural_language_filter.api.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ src/
COPY run.py .

EXPOSE 8000
CMD ["python", "run.py"]
```

## Troubleshooting

### Common Issues

1. **OpenAI API Key Missing**
   ```
   Error: OPENAI_API_KEY environment variable is required
   ```
   Solution: Set your OpenAI API key in the `.env` file or environment variables.

2. **Filter API Connection Error**
   ```
   Error fetching values for filter 'account_type': HTTP 404
   ```
   Solution: Verify the `FILTER_API_BASE_URL` is correct and the reporting service is accessible.

3. **Permission Denied**
   ```
   Error: Failed to fetch values for filter 'account_type': HTTP 401
   ```
   Solution: Set the `FILTER_API_AUTH_TOKEN` if the reporting service requires authentication.

### Debug Mode

Enable debug mode for detailed logging:

```bash
DEBUG=true python run.py
```

This will show detailed request/response information and error traces.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

MIT License - see LICENSE file for details.
