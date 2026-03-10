# Use the Fedora-based image you just pushed
FROM yashwild/omnis:v1

# 4. Copy files from repo to home directory
COPY . .

# 5. Install python3 requirements
RUN pip3 install -r requirements.txt

# 6. cleanup for arm64
RUN if [[ $(arch) == 'aarch64' ]]; then dnf -qq -y history undo last; fi && dnf clean all

# 7. Start bot
CMD ["bash","run.sh"]
