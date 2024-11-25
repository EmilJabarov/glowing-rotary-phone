import openai

def modify_query_with_preferences(query, preferences):
    logging.debug(f"Modifying query: '{query}' with preferences: '{preferences}'")  # Log query modification
    try:
        # Corrected OpenAI API call using chat/completion endpoint
        response = openai.ChatCompletion.create(
            model="gpt-4",  # Use 'gpt-3.5-turbo' or 'gpt-4'
            messages=[
                {"role": "system", "content": "You are an assistant that personalizes search queries based on user preferences."},
                {"role": "user", "content": f"Preferences: {preferences}"},
                {"role": "user", "content": f"Original Query: {query}"}
            ],
            temperature=0.5,
            max_tokens=100
        )
        modified_query = response['choices'][0]['message']['content'].strip()
        logging.debug(f"Modified query: {modified_query}")  # Log the modified query
        return modified_query
    except Exception as e:
        logging.error(f"Error modifying query: {e}", exc_info=True)
        return query  # Fall back to the original query if API call fails
