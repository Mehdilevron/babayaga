"""Memecoin scanner: pulls freshly listed/promoted tokens from DexScreener,
filters out the obvious rug shapes, ranks the rest by liquidity and short-term
momentum, and optionally pushes alerts to Telegram.

This is a watchlist tool, not a predictor - a high score means "this token is
currently liquid and active", nothing more. It never trades.
"""
