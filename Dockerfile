# Use the Fedora-based image you just pushed
FROM yashwild/omnis:v1

# Set working directory
WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

# Create virtual environment using uv (WZML style)
RUN /uv/bin/uv venv --system-site-packages

# Install requirements
COPY requirements.txt .
RUN /uv/bin/uv pip install --no-cache-dir -r requirements.txt

# Copy your bot code
COPY . .

# Start the bot
CMD ["bash", "run.sh"]
