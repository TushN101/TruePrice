

# Install the required packages

pip install -r requirements.txt


# Install mongodb

sudo docker run -d \
  --name mongodb \
  -p 27017:27017 \
  -v mongodb_data:/data/db \
  mongo:8
