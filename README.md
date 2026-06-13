# Wordle Scoreboard

Head-to-head Wordle scoreboard for a WhatsApp chat where two players share their daily `Wordle N X/6` results. 

A manual chat export is uploaded to S3, which kicks off a serverless pipeline that updates the running score, and a Streamlit app
renders the scoreboard.

