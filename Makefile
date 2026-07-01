# Makefile for AI-Powered GitHub Workflows

.PHONY: check test clean

# 检查 Python 环境和依赖是否就绪
check:
	@echo "🔍 Checking Python environment..."
	@python3 --version || (echo "❌ Python3 not found" && exit 1)
	@pip --version || (echo "❌ pip not found" && exit 1)
	@echo "✅ Python environment OK"
	@echo "🔍 Checking dependencies..."
	@pip install -q -e . 2>/dev/null && echo "✅ Dependencies installed" || (echo "❌ Failed to install dependencies" && exit 1)

# 运行所有脚本的语法检查
test:
	@echo "🧪 Running syntax checks..."
	@python3 -m py_compile .github/scripts/*.py && echo "✅ All scripts syntax OK" || (echo "❌ Syntax error found" && exit 1)

# 清理 __pycache__ 和 .pyc 文件
clean:
	@echo "🧹 Cleaning up..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; echo "✅ Removed __pycache__ directories"
	@find . -type f -name "*.pyc" -delete && echo "✅ Removed .pyc files"
