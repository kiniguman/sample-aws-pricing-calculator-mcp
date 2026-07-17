FROM node:22-alpine
WORKDIR /app
RUN npm install -g sample-aws-pricing-calculator-mcp@latest
EXPOSE 3000
ENV MCP_TRANSPORT=http
ENV PORT=3000
CMD ["sample-aws-pricing-calculator-mcp"]
