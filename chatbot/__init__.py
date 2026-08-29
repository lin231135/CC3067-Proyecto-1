"""Chatbot host for CC3067 Project 1.

Coordinates multiple MCP clients (Filesystem, Git, and the custom LIMS
server) and an Anthropic Messages API connection. Built without any MCP
SDK: chatbot/mcp/ implements the client side of MCP by hand, the same way
lims_mcp_server/ implements the server side.
"""
