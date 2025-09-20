# SAP Knowledge Base Frontend

Modern Next.js 14 frontend for the SAP Knowledge Base system with TypeScript, Chakra UI, and TanStack Query.

## Features

- **Modern UI**: Built with Chakra UI and Tailwind CSS for a responsive, accessible interface
- **Type Safety**: Full TypeScript support with strict type checking
- **State Management**: TanStack Query for server state management and caching
- **API Integration**: Axios-based client with automatic error handling and retries
- **Docker Support**: Multi-stage Dockerfile for optimized production builds
- **Health Monitoring**: Built-in health check endpoint for container orchestration

## Architecture

### Pages Structure
- `/chat` - GPT-like chat interface with streaming responses
- `/documents` - Document management (list, upload, details)
- `/admin` - Administration dashboard with system monitoring

### Components
- `MainLayout` - Global layout with sidebar and header
- `Sidebar` - Responsive navigation with mobile support
- `Header` - Top navigation bar with user menu

### API Client
- Type-safe API client with automatic error handling
- Built-in retry logic for network failures
- Request/response interceptors for authentication
- Environment-based configuration

## Quick Start

### Development
```bash
npm install
npm run dev
```

### Production with Docker
```bash
# Build and run the entire stack
docker-compose up -d frontend

# Access the application
http://localhost:3000
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_BASE_URL` | Backend API URL | `http://localhost:8000` |
| `NODE_ENV` | Environment mode | `development` |
| `PORT` | Server port | `3000` |

## API Integration

The frontend communicates with the FastAPI backend through:
- **API Rewrites**: `/api/*` routes are proxied to the backend
- **Type Safety**: TypeScript interfaces for all API responses
- **Error Handling**: Centralized error management with user feedback
- **Caching**: Intelligent caching with TanStack Query

## Docker Configuration

### Multi-stage Build
1. **Builder**: Install dependencies and build the application
2. **Runner**: Minimal production image with only necessary files

### Health Checks
- Container health monitoring via `/api/health` endpoint
- Automatic restart on health check failures
- Integration with docker-compose orchestration

## Development Guidelines

### Code Organization
- Pages in `src/app/` following Next.js 13+ app directory structure
- Reusable components in `src/components/`
- API logic in `src/lib/api.ts`
- Type definitions in `src/types/`

### Styling
- Chakra UI for component library
- Tailwind CSS for utility classes
- Custom theme configuration in `src/lib/theme.ts`
- Responsive design with mobile-first approach

## Troubleshooting

### Common Issues
1. **API Connection**: Verify `NEXT_PUBLIC_API_BASE_URL` points to running backend
2. **Build Failures**: Check Node.js version (requires 18+)
3. **Docker Issues**: Ensure backend service is running before frontend
4. **Type Errors**: Run `npm run type-check` to identify TypeScript issues

### Logs
```bash
# Container logs
docker logs knowbase-frontend

# Development logs
npm run dev
```