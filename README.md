# Zmordle 

Zmordle is a Wordle scoreboard between 2 friends
fed by a WhatsApp chat where two players share their daily `Wordle N X/6` results. 

Since there is no Whatsapp API, zmordle works by:  
- ingesting the chat export into s3,
- regex parses for test results
- triggers a serverless pipeline to update the scoreboard analytics,

a Streamlit app renders the scoreboard.

Deployed at: 
https://zmordle.up.railway.app/ 
